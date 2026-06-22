import json

from EvernightAI.core.protocol.skill import SkillRegisterProtocol
from EvernightAI.core.schema.content import Content, ContentPart, ContentPartType, MessageRole
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)


def register_echo_skill(register: SkillRegisterProtocol) -> None:
    register.register(
        SkillDefinition(
            name="echo",
            description="Render the skill variables into a system prompt.",
            input_schema={"type": "object"},
            output_schema={
                "type": "object",
                "properties": {"messages": {"type": "array"}},
                "required": ["messages"],
            },
            capabilities=[SkillCapability.AGENT],
            metadata={"builtin": True},
        ),
        _render_echo,
    )


async def _render_echo(request: SkillRenderRequest) -> RenderedSkill:
    variables = json.dumps(request.variables, ensure_ascii=False)
    return RenderedSkill(
        render_id=request.render_id,
        skill_name=request.skill_name,
        messages=[
            Content(
                role=MessageRole.SYSTEM,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=f"Echo skill variables: {variables}",
                    )
                ],
            )
        ],
        metadata={"builtin": "echo"},
    )
