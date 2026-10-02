from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime, create_sqlite_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedSkillInterface
from EvernightAI.core.domain.skill import SkillManager, SkillRegister
from EvernightAI.core.protocol.skill import SkillTemplateStoreProtocol
from EvernightAI.core.error.auth import AuthPermissionDeniedError
from EvernightAI.core.error.skill import SkillConfigurationError, SkillConflictError, SkillDisabledError, SkillInputError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.content import ChatRequest, ChatSkill
from EvernightAI.core.schema.skill import SkillCapability, SkillRenderRequest, SkillTemplateConfig, SkillTemplateUpdate
from EvernightAI.core.schema.tool import ToolDefinition
from EvernightAI.application.skill_prompt import compose_skill_prompted_chat_request
from EvernightAI.infra.adapters.skill.template import create_template_renderer
from EvernightAI.infra.adapters.skill.sqlite import SQLiteSkillTemplateStore
from EvernightAI.interface.http.app import create_http_app


def template(**updates: object) -> SkillTemplateConfig:
    return SkillTemplateConfig.model_validate({
        "name": "style", "description": "Style instructions", "prompt": "Use $tone style. $$5 ${count}",
        "capabilities": ["chat", "agent"],
        "input_schema": {"type": "object", "properties": {"tone": {"type": "string"}}, "required": ["tone"]},
        **updates,
    })


@pytest.mark.asyncio
async def test_template_rendering_is_literal_and_repeated() -> None:
    runtime = create_runtime()
    manager = runtime.skills
    manager.create_template(template())
    for _ in range(2):
        rendered = await manager.render(SkillRenderRequest(
            skill_name="style", render_id="render", variables={"tone": "${other}", "count": {"value": 3}},
        ))
        assert rendered.messages[0].content is not None
        assert rendered.messages[0].content[0].text == 'Use ${other} style. $5 {"value": 3}'
    with pytest.raises(SkillInputError, match="Missing template variables"):
        await manager.render(SkillRenderRequest(skill_name="style", render_id="render", variables={"tone": "calm"}))
    with pytest.raises(SkillConfigurationError):
        manager.create_template(template(name="invalid", prompt="${broken"))
    assert [skill.name for skill in manager.list_skills()] == ["echo", "style"]
    await runtime.close()


@pytest.mark.asyncio
async def test_sqlite_templates_restore_updates_disabled_state_and_delete(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    runtime = create_sqlite_runtime(database)
    await runtime.initialize()
    runtime.skills.create_template(template(prompt="Use $tone style"))
    with pytest.raises(SkillConflictError):
        runtime.skills.create_template(template())
    runtime.skills.update_template("style", SkillTemplateUpdate(description="Updated", is_enabled=False))
    await runtime.close()
    reopened = create_sqlite_runtime(database)
    await reopened.initialize()
    assert reopened.skills.get_template("style").description == "Updated"
    assert reopened.skills.get_skill("style").is_enabled is False
    assert reopened.skills.supports("style", SkillCapability.CHAT) is False
    with pytest.raises(SkillDisabledError):
        await reopened.skills.render(SkillRenderRequest(skill_name="style", render_id="render"))
    with pytest.raises(SkillDisabledError):
        reopened.skills.validate_input(SkillRenderRequest(skill_name="style", render_id="render"))
    reopened.skills.update_template("style", SkillTemplateUpdate(is_enabled=True))
    result = await reopened.skills.render(SkillRenderRequest(skill_name="style", render_id="render", variables={"tone": "calm"}))
    assert result.messages[0].content is not None
    assert result.messages[0].content[0].text == "Use calm style"
    reopened.skills.delete_template("style")
    await reopened.close()
    deleted = create_sqlite_runtime(database)
    await deleted.initialize()
    assert [skill.name for skill in deleted.skills.list_skills()] == ["echo"]
    await deleted.close()


class FailingStore(SkillTemplateStoreProtocol):
    fail = False

    def save(self, config: SkillTemplateConfig) -> None:
        if self.fail:
            raise RuntimeError("storage unavailable")

    def list_configs(self) -> list[SkillTemplateConfig]:
        return []

    def delete(self, skill_name: str) -> None:
        if self.fail:
            raise RuntimeError("storage unavailable")

    def close(self) -> None:
        pass

    def is_ready(self) -> bool:
        return True


def test_failed_persistence_does_not_publish_create_update_or_delete() -> None:
    store = FailingStore()
    manager = SkillManager(SkillRegister(), template_factory=create_template_renderer, template_store=store)
    store.fail = True
    with pytest.raises(RuntimeError):
        manager.create_template(template())
    assert manager.list_skills() == []
    store.fail = False
    manager.create_template(template())
    revision = manager.get_template("style").revision
    store.fail = True
    with pytest.raises(RuntimeError):
        manager.update_template("style", SkillTemplateUpdate(is_enabled=False))
    with pytest.raises(RuntimeError):
        manager.delete_template("style")
    assert manager.get_skill("style").is_enabled
    assert manager.get_template("style").is_enabled
    assert manager.get_template("style").revision == revision


def test_template_revisions_are_server_owned_and_change_only_with_config() -> None:
    manager = SkillManager(SkillRegister(), template_factory=create_template_renderer)
    created = manager.create_template(template(revision="client-version"))
    assert created.revision is not None and created.revision != "client-version"
    assert manager.update_template("style", SkillTemplateUpdate()).revision == created.revision
    assert manager.update_template("style", SkillTemplateUpdate(description=created.description)).revision == created.revision
    updated = manager.update_template("style", SkillTemplateUpdate(description="Updated description"))
    assert updated.revision != created.revision
    assert manager.get_template("style").revision == updated.revision
    with pytest.raises(SkillConfigurationError):
        manager.update_template("style", SkillTemplateUpdate(prompt="${broken"))
    assert manager.get_template("style").revision == updated.revision
    manager.delete_template("style")
    recreated = manager.create_template(template(revision=created.revision))
    assert recreated.revision not in {created.revision, updated.revision}


@pytest.mark.asyncio
async def test_legacy_template_gets_a_stable_persisted_revision(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    store = SQLiteSkillTemplateStore(database)
    store.save(template(is_template=True))
    store.close()
    runtime = create_sqlite_runtime(database)
    await runtime.initialize()
    revision = runtime.skills.get_template("style").revision
    assert revision is not None
    await runtime.close()
    reopened = create_sqlite_runtime(database)
    await reopened.initialize()
    assert reopened.skills.get_template("style").revision == revision
    assert reopened.skills.get_skill("style").revision == revision
    await reopened.close()


@pytest.mark.asyncio
async def test_skill_dependencies_do_not_automatically_grant_tools() -> None:
    runtime = create_runtime()
    runtime.skills.create_template(template(prompt="Use $tone", required_tools=["read_text_file"]))
    request = ChatRequest(model_id="model", messages=[], skills=[ChatSkill(skill_name="style", variables={"tone": "calm"})])
    with pytest.raises(SkillInputError, match="requires tools"):
        await compose_skill_prompted_chat_request(runtime, request, SkillCapability.AGENT)
    tool = ToolDefinition(name="read_text_file", description="Read")
    composed = await compose_skill_prompted_chat_request(runtime, request.model_copy(update={"tools": [tool]}), SkillCapability.AGENT)
    assert composed.tools == [tool]
    await runtime.close()


def test_skill_http_management_and_builtin_protection() -> None:
    with TestClient(create_http_app(create_interface(create_runtime()))) as client:
        body = template(prompt="Use $tone").model_dump(mode="json")
        assert client.post("/skills", json=body).status_code == 201
        assert client.post("/skills", json=body).status_code == 409
        assert client.get("/skills/style/template").json()["prompt"] == "Use $tone"
        assert client.patch("/skills/style", json={"is_enabled": False}).status_code == 200
        assert client.post("/skills/style/render", json={"variables": {"tone": "calm"}}).status_code == 409
        assert client.patch("/skills/echo", json={"is_enabled": False}).status_code == 400
        assert client.delete("/skills/echo").status_code == 400
        assert client.patch("/skills/style", json={"name": "renamed"}).status_code == 400
        assert client.patch("/skills/style", json={"prompt": "${broken"}).status_code == 400
        assert client.get("/skills/style/template").json()["prompt"] == "Use $tone"
        assert client.delete("/skills/style").status_code == 204
        assert client.get("/skills/style").status_code == 404


@pytest.mark.parametrize("entrypoint", ["render", "compose-preview"])
def test_skill_http_returns_configuration_error_for_nonterminating_schema(entrypoint: str) -> None:
    with TestClient(create_http_app(create_interface(create_runtime()))) as client:
        assert client.post("/skills", json=template(prompt="Literal", input_schema={"$ref": "#"}).model_dump(mode="json")).status_code == 201
        if entrypoint == "render":
            response = client.post("/skills/style/render", json={"variables": {}})
        else:
            assert client.post("/contexts", json={"context_id": "probe"}).status_code == 201
            response = client.post("/contexts/probe/compose-preview", json={
                "model_id": "model", "skills": [{"skill_name": "style"}],
            })
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "SkillConfigurationError"


@pytest.mark.parametrize("action", ["create", "get_template", "update", "delete"])
@pytest.mark.asyncio
async def test_skill_management_has_separate_permissions(action: str) -> None:
    runtime = create_runtime()
    runtime.skills.create_template(template())
    interface = AuthorizedSkillInterface(create_interface(runtime).skills, Authorizer(PermissionAuthPolicy()),
                                         Principal(principal_id="user", permissions=["skills:list", "skills:get", "skills:render"]))
    with pytest.raises(AuthPermissionDeniedError):
        if action == "create":
            interface.create_template(template(name="another"))
        elif action == "get_template":
            interface.get_template("style")
        elif action == "update":
            interface.update_template("style", SkillTemplateUpdate(is_enabled=False))
        else:
            interface.delete_template("style")
    await runtime.close()
