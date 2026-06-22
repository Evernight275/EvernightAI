import pytest

from EvernightAI.application.skill import SkillApplication
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillRenderRequest,
    SkillCapability,
    SkillDefinition,
)


@pytest.mark.asyncio
async def test_skill_application_lists_and_executes_runtime_skills() -> None:
    async def summarize(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
            messages=[make_system_message(str(request.variables["text"]))],
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

    rendered = await application.render_skill(
        SkillRenderRequest(
            render_id="skill-render-1",
            skill_name="summarize",
            variables={"text": "hello"},
        )
    )

    assert [skill.name for skill in application.list_skills()] == [
        "echo",
        "summarize",
    ]
    assert application.get_skill("summarize").name == "summarize"
    assert application.skill_supports("summarize", SkillCapability.CHAT) is True
    assert rendered.messages == [make_system_message("hello")]


def make_system_message(text: str) -> Content:
    return Content(
        role=MessageRole.SYSTEM,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )
