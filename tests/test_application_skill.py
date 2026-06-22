import pytest

from EvernightAI.application.skill import SkillApplication
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.schema.skill import (
    SkillCall,
    SkillCapability,
    SkillDefinition,
    SkillResult,
)


@pytest.mark.asyncio
async def test_skill_application_lists_and_executes_runtime_skills() -> None:
    async def summarize(call: SkillCall) -> SkillResult:
        return SkillResult(
            skill_call_id=call.skill_call_id,
            skill_name=call.skill_name,
            result={"summary": call.arguments["text"]},
        )

    runtime = create_runtime()
    runtime.skill_register.register(
        SkillDefinition(
            name="summarize",
            description="Summarize text",
            capabilities=[SkillCapability.CHAT],
        ),
        summarize,
    )
    application = SkillApplication(runtime)

    result = await application.execute_skill(
        SkillCall(
            skill_call_id="skill-call-1",
            skill_name="summarize",
            arguments={"text": "hello"},
        )
    )

    assert [skill.name for skill in application.list_skills()] == [
        "echo",
        "summarize",
    ]
    assert application.get_skill("summarize").name == "summarize"
    assert application.skill_supports("summarize", SkillCapability.CHAT) is True
    assert result.result == {"summary": "hello"}
