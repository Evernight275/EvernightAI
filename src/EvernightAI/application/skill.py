from EvernightAI.core.protocol.interface import SkillInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.skill import SkillCall, SkillDefinition, SkillResult


class SkillApplication(SkillInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    def list_skills(self) -> list[SkillDefinition]:
        return self._runtime.skills.list_skills()

    async def execute_skill(self, call: SkillCall) -> SkillResult:
        return await self._runtime.skills.execute(call)
