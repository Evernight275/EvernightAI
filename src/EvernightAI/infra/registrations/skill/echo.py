from EvernightAI.core.protocol.skill import SkillRegisterProtocol
from EvernightAI.core.schema.skill import (
    SkillCall,
    SkillCapability,
    SkillDefinition,
    SkillResult,
)


def register_echo_skill(register: SkillRegisterProtocol) -> None:
    register.register(
        SkillDefinition(
            name="echo",
            description="Return the skill call arguments unchanged.",
            input_schema={"type": "object"},
            output_schema={
                "type": "object",
                "properties": {"echo": {"type": "object"}},
                "required": ["echo"],
            },
            capabilities=[SkillCapability.AGENT],
            metadata={"builtin": True},
        ),
        _execute_echo,
    )


async def _execute_echo(call: SkillCall) -> SkillResult:
    return SkillResult(
        skill_call_id=call.skill_call_id,
        skill_name=call.skill_name,
        result={"echo": dict(call.arguments)},
        metadata={"builtin": "echo"},
    )
