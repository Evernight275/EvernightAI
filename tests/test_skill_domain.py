import json

import pytest

from EvernightAI.core.domain.skill import SkillManager, SkillRegister
from EvernightAI.core.error.skill import (
    SkillConfigurationError,
    SkillInputError,
    SkillNotFoundError,
    SkillRenderError,
)
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)


def make_skill() -> SkillDefinition:
    return SkillDefinition(
        name="summarize",
        description="Summarize text",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
        capabilities=[SkillCapability.CHAT],
        required_tools=["read_text_file"],
    )


@pytest.mark.asyncio
async def test_skill_manager_renders_registered_skill() -> None:
    async def summarize(request: SkillRenderRequest) -> RenderedSkill:
        text = request.variables["text"]
        assert isinstance(text, str)
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
            messages=[make_system_message(text[:5])],
        )

    register = SkillRegister()
    register.register(make_skill(), summarize)
    manager = SkillManager(register)

    rendered = await manager.render(
        SkillRenderRequest(
            render_id="skill-render-1",
            skill_name="summarize",
            variables={"text": "hello world"},
        )
    )

    assert manager.list_skills() == [make_skill()]
    assert rendered.render_id == "skill-render-1"
    assert rendered.skill_name == "summarize"
    assert rendered.messages == [make_system_message("hello")]


def test_skill_register_raises_for_missing_skill() -> None:
    register = SkillRegister()

    with pytest.raises(SkillNotFoundError):
        register.get("missing")


def test_skill_manager_gets_skill_and_checks_capability() -> None:
    register = SkillRegister()
    manager = SkillManager(register)

    async def summarize(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
        )

    register.register(make_skill(), summarize)

    assert manager.get_skill("summarize") == make_skill()
    assert manager.supports("summarize", SkillCapability.CHAT) is True
    assert manager.supports("summarize", SkillCapability.AGENT) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skill_name, render_id", [("", "probe"), (" ", "probe"), ("summarize", " ")]
)
async def test_skill_manager_rejects_missing_identity(
    skill_name: str, render_id: str
) -> None:
    manager = SkillManager(SkillRegister())

    with pytest.raises(SkillInputError):
        await manager.render(
            SkillRenderRequest(render_id=render_id, skill_name=skill_name)
        )


@pytest.mark.asyncio
async def test_skill_manager_wraps_renderer_errors() -> None:
    async def broken(_request: SkillRenderRequest) -> RenderedSkill:
        raise RuntimeError("boom")

    register = SkillRegister()
    register.register(make_skill(), broken)
    manager = SkillManager(register)

    with pytest.raises(SkillRenderError) as exc_info:
        await manager.render(
            SkillRenderRequest(
                render_id="skill-render-1",
                skill_name="summarize",
                variables={"text": "hello"},
            )
        )

    assert isinstance(exc_info.value.cause, RuntimeError)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variables, path, constraint",
    [
        ({}, ["variables"], "required"),
        ({"text": 3}, ["variables", "text"], "type"),
    ],
)
async def test_skill_manager_rejects_input_before_renderer(
    variables: dict[str, object],
    path: list[str],
    constraint: str,
) -> None:
    async def unexpected(_request: SkillRenderRequest) -> RenderedSkill:
        pytest.fail("Invalid variables must not reach the renderer")

    register = SkillRegister()
    register.register(make_skill(), unexpected)
    with pytest.raises(SkillInputError) as caught:
        await SkillManager(register).render(
            SkillRenderRequest(
                render_id="probe",
                skill_name="summarize",
                variables=variables,
            )
        )
    assert caught.value.detail is not None
    detail = json.loads(caught.value.detail)
    assert detail["path"] == path
    assert detail["constraint"] == constraint


@pytest.mark.asyncio
async def test_skill_manager_reports_nested_array_path_without_echoing_values() -> None:
    async def unexpected(_request: SkillRenderRequest) -> RenderedSkill:
        pytest.fail("Invalid variables must not reach the renderer")

    register = SkillRegister()
    register.register(
        SkillDefinition(
            name="nested",
            description="Nested parameters",
            input_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "count": {"type": "integer"},
                            },
                        },
                    }
                },
            },
        ),
        unexpected,
    )
    with pytest.raises(SkillInputError) as caught:
        await SkillManager(register).render(
            SkillRenderRequest(
                render_id="probe",
                skill_name="nested",
                variables={"items": [{"count": "private-input"}]},
            )
        )
    assert caught.value.detail is not None
    assert json.loads(caught.value.detail) == {
        "path": ["variables", "items", 0, "count"],
        "schema_path": ["properties", "items", "items", "properties", "count", "type"],
        "constraint": "type",
    }
    assert "private-input" not in str(caught.value) + caught.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("error_class", [SkillInputError, SkillRenderError])
async def test_skill_manager_preserves_renderer_domain_error(
    error_class: type[SkillInputError | SkillRenderError],
) -> None:
    error = error_class("Invalid combination", detail="Choose one option")

    async def invalid(_request: SkillRenderRequest) -> RenderedSkill:
        raise error

    register = SkillRegister()
    register.register(make_skill(), invalid)
    with pytest.raises(error_class) as caught:
        await SkillManager(register).render(
            SkillRenderRequest(
                render_id="probe",
                skill_name="summarize",
                variables={"text": "hello"},
            )
        )
    assert caught.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["skill_name", "render_id"])
async def test_skill_manager_rejects_mismatched_renderer_identity(field: str) -> None:
    async def mismatched(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id, skill_name=request.skill_name
        ).model_copy(
            update={field: "wrong"},
        )

    register = SkillRegister()
    register.register(make_skill(), mismatched)
    with pytest.raises(SkillRenderError, match="mismatched"):
        await SkillManager(register).render(
            SkillRenderRequest(
                render_id="probe",
                skill_name="summarize",
                variables={"text": "hello"},
            )
        )


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "unknown"},
        {"required": "text"},
        {"$schema": "https://example.invalid/unknown-schema"},
        {"$schema": []},
    ],
)
def test_skill_register_rejects_invalid_schema_before_replacing_skill(
    schema: dict[str, object],
) -> None:
    async def renderer(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(render_id=request.render_id, skill_name=request.skill_name)

    register = SkillRegister()
    register.register(make_skill(), renderer)
    with pytest.raises(SkillConfigurationError):
        register.register(
            make_skill().model_copy(update={"input_schema": schema}), renderer
        )
    assert register.get("summarize") == make_skill()
    assert register.get_renderer("summarize") is renderer


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [None, {}, {"type": "object"}])
async def test_skill_manager_keeps_schema_optional(
    schema: dict[str, object] | None,
) -> None:
    async def renderer(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(render_id=request.render_id, skill_name=request.skill_name)

    register = SkillRegister()
    register.register(
        make_skill().model_copy(update={"input_schema": schema}), renderer
    )
    assert (
        await SkillManager(register).render(
            SkillRenderRequest(
                render_id="probe",
                skill_name="summarize",
            )
        )
    ).render_id == "probe"


@pytest.mark.asyncio
async def test_skill_manager_validates_local_refs_without_coercion_or_defaults() -> (
    None
):
    async def renderer(request: SkillRenderRequest) -> RenderedSkill:
        assert request.variables == {"count": 3}
        return RenderedSkill(render_id=request.render_id, skill_name=request.skill_name)

    register = SkillRegister()
    register.register(
        SkillDefinition(
            name="local",
            description="Local references",
            input_schema={
                "$defs": {"count": {"type": "integer", "minimum": 1}},
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "count": {"$ref": "#/$defs/count"},
                    "optional": {"type": "string", "default": "not-inserted"},
                },
                "required": ["count"],
            },
        ),
        renderer,
    )
    manager = SkillManager(register)
    request = SkillRenderRequest(
        render_id="probe", skill_name="local", variables={"count": 3}
    )
    await manager.render(request)
    assert request.variables == {"count": 3}
    for variables in [{"count": "3"}, {"count": 0}, {"count": 3, "extra": True}]:
        with pytest.raises(SkillInputError):
            await manager.render(request.model_copy(update={"variables": variables}))


@pytest.mark.asyncio
async def test_skill_manager_honors_explicit_legacy_draft() -> None:
    async def renderer(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(render_id=request.render_id, skill_name=request.skill_name)

    register = SkillRegister()
    register.register(
        SkillDefinition(
            name="legacy",
            description="Draft 4",
            input_schema={
                "$schema": "http://json-schema.org/draft-04/schema#",
                "type": "object",
                "properties": {
                    "count": {"type": "number", "minimum": 1, "exclusiveMinimum": True}
                },
            },
        ),
        renderer,
    )
    manager = SkillManager(register)
    await manager.render(
        SkillRenderRequest(
            render_id="probe", skill_name="legacy", variables={"count": 2}
        )
    )
    with pytest.raises(SkillInputError):
        await manager.render(
            SkillRenderRequest(
                render_id="probe", skill_name="legacy", variables={"count": 1}
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference", ["#/$defs/missing", "https://example.invalid/schema.json"]
)
async def test_skill_manager_rejects_unresolvable_references_without_network(
    reference: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_network(*args: object, **kwargs: object) -> None:
        pytest.fail("Schema validation must not make network requests")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_network)

    async def unexpected(_request: SkillRenderRequest) -> RenderedSkill:
        pytest.fail("Unresolved references must not reach the renderer")

    register = SkillRegister()
    register.register(
        SkillDefinition(
            name="ref", description="Reference", input_schema={"$ref": reference}
        ),
        unexpected,
    )
    with pytest.raises(SkillConfigurationError, match="unresolved reference"):
        await SkillManager(register).render(
            SkillRenderRequest(render_id="probe", skill_name="ref")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "#"},
        {
            "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}},
            "$ref": "#/$defs/a",
        },
    ],
)
@pytest.mark.parametrize("entrypoint", ["validate_input", "render"])
async def test_skill_manager_translates_nonterminating_schema_recursion(
    schema: dict[str, object],
    entrypoint: str,
) -> None:
    async def unexpected(_request: SkillRenderRequest) -> RenderedSkill:
        pytest.fail("Recursive validation failure must not reach the renderer")

    register = SkillRegister()
    register.register(
        SkillDefinition(
            name="recursive", description="Recursive schema", input_schema=schema
        ),
        unexpected,
    )
    manager = SkillManager(register)
    request = SkillRenderRequest(render_id="probe", skill_name="recursive")
    with pytest.raises(SkillConfigurationError, match="validation depth") as caught:
        if entrypoint == "validate_input":
            manager.validate_input(request)
        else:
            await manager.render(request)
    assert isinstance(caught.value.cause, RecursionError)


@pytest.mark.asyncio
async def test_skill_manager_accepts_terminating_recursive_schema() -> None:
    async def renderer(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(render_id=request.render_id, skill_name=request.skill_name)

    register = SkillRegister()
    register.register(
        SkillDefinition(
            name="tree",
            description="Recursive tree",
            input_schema={
                "type": "object",
                "properties": {
                    "value": {"type": "integer"},
                    "children": {"type": "array", "items": {"$ref": "#"}},
                },
                "required": ["value"],
            },
        ),
        renderer,
    )
    manager = SkillManager(register)
    request = SkillRenderRequest(
        render_id="probe",
        skill_name="tree",
        variables={
            "value": 1,
            "children": [{"value": 2, "children": [{"value": 3}]}],
        },
    )
    assert (await manager.render(request)).render_id == "probe"
    with pytest.raises(SkillInputError):
        await manager.render(
            request.model_copy(
                update={"variables": {"value": 1, "children": [{"value": "bad"}]}}
            )
        )


def test_skill_register_unregisters_skill() -> None:
    async def summarize(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
        )

    register = SkillRegister()
    register.register(make_skill(), summarize)

    register.unregister("summarize")

    assert register.has("summarize") is False


def make_system_message(text: str) -> Content:
    return Content(
        role=MessageRole.SYSTEM,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )
