import pytest

from EvernightAI.application.skill import SkillApplication
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.schema.skill import SkillCall, SkillDefinition, SkillResult


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
        SkillDefinition(name="summarize", description="Summarize text"),
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

    assert application.list_skills() == [
        SkillDefinition(name="summarize", description="Summarize text")
    ]
    assert result.result == {"summary": "hello"}
