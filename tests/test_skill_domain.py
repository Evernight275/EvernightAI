import pytest

from EvernightAI.core.domain.skill import SkillManager, SkillRegister
from EvernightAI.core.error.skill import (
    SkillExecutionError,
    SkillInputError,
    SkillNotFoundError,
)
from EvernightAI.core.schema.skill import (
    SkillCall,
    SkillCapability,
    SkillDefinition,
    SkillResult,
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
async def test_skill_manager_executes_registered_skill() -> None:
    async def summarize(call: SkillCall) -> SkillResult:
        text = call.arguments["text"]
        assert isinstance(text, str)
        return SkillResult(
            skill_call_id=call.skill_call_id,
            skill_name=call.skill_name,
            result={"summary": text[:5]},
        )

    register = SkillRegister()
    register.register(make_skill(), summarize)
    manager = SkillManager(register)

    result = await manager.execute(
        SkillCall(
            skill_call_id="skill-call-1",
            skill_name="summarize",
            arguments={"text": "hello world"},
        )
    )

    assert manager.list_skills() == [make_skill()]
    assert result.skill_call_id == "skill-call-1"
    assert result.skill_name == "summarize"
    assert result.result == {"summary": "hello"}


def test_skill_register_raises_for_missing_skill() -> None:
    register = SkillRegister()

    with pytest.raises(SkillNotFoundError):
        register.get("missing")


def test_skill_manager_gets_skill_and_checks_capability() -> None:
    register = SkillRegister()
    manager = SkillManager(register)

    async def summarize(call: SkillCall) -> SkillResult:
        return SkillResult(
            skill_call_id=call.skill_call_id,
            skill_name=call.skill_name,
        )

    register.register(make_skill(), summarize)

    assert manager.get_skill("summarize") == make_skill()
    assert manager.supports("summarize", SkillCapability.CHAT) is True
    assert manager.supports("summarize", SkillCapability.AGENT) is False


@pytest.mark.asyncio
async def test_skill_manager_rejects_missing_skill_name() -> None:
    manager = SkillManager(SkillRegister())

    with pytest.raises(SkillInputError):
        await manager.execute(
            SkillCall(skill_call_id="skill-call-1", skill_name="")
        )


@pytest.mark.asyncio
async def test_skill_manager_wraps_executor_errors() -> None:
    async def broken(_call: SkillCall) -> SkillResult:
        raise RuntimeError("boom")

    register = SkillRegister()
    register.register(make_skill(), broken)
    manager = SkillManager(register)

    with pytest.raises(SkillExecutionError) as exc_info:
        await manager.execute(
            SkillCall(skill_call_id="skill-call-1", skill_name="summarize")
        )

    assert isinstance(exc_info.value.cause, RuntimeError)


def test_skill_register_unregisters_skill() -> None:
    async def summarize(call: SkillCall) -> SkillResult:
        return SkillResult(
            skill_call_id=call.skill_call_id,
            skill_name=call.skill_name,
        )

    register = SkillRegister()
    register.register(make_skill(), summarize)

    register.unregister("summarize")

    assert register.has("summarize") is False
