from EvernightAI.core.protocol.interface import SkillInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.skill import (
    SkillCall,
    SkillCapability,
    SkillDefinition,
    SkillResult,
)


class SkillApplication(SkillInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    def list_skills(self) -> list[SkillDefinition]:
        return self._runtime.skills.list_skills()

    def get_skill(self, skill_name: str) -> SkillDefinition:
        return self._runtime.skills.get_skill(skill_name)

    def skill_supports(self, skill_name: str, capability: SkillCapability) -> bool:
        return self._runtime.skills.supports(skill_name, capability)

    async def execute_skill(self, call: SkillCall) -> SkillResult:
        return await self._runtime.skills.execute(call)
