import pytest

from EvernightAI.core.domain.skill import SkillManager, SkillRegister
from EvernightAI.core.error.skill import (
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
async def test_skill_manager_rejects_missing_skill_name() -> None:
    manager = SkillManager(SkillRegister())

    with pytest.raises(SkillInputError):
        await manager.render(
            SkillRenderRequest(render_id="skill-render-1", skill_name="")
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
            SkillRenderRequest(render_id="skill-render-1", skill_name="summarize")
        )

    assert isinstance(exc_info.value.cause, RuntimeError)


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
