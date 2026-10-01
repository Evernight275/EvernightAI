from EvernightAI.core.protocol.interface import SkillInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillRenderRequest,
    SkillCapability,
    SkillDefinition,
    SkillTemplateConfig,
    SkillTemplateUpdate,
)


class SkillApplication(SkillInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    def list_skills(self) -> list[SkillDefinition]:
        return self._runtime.skills.list_skills()

    def create_skill(self, config: SkillTemplateConfig) -> SkillDefinition:
        return self._runtime.skills.create_template(config)

    def get_skill_template(self, skill_name: str) -> SkillTemplateConfig:
        return self._runtime.skills.get_template(skill_name)

    def update_skill(self, skill_name: str, update: SkillTemplateUpdate) -> SkillDefinition:
        return self._runtime.skills.update_template(skill_name, update)

    def delete_skill(self, skill_name: str) -> None:
        self._runtime.skills.delete_template(skill_name)

    def get_skill(self, skill_name: str) -> SkillDefinition:
        return self._runtime.skills.get_skill(skill_name)

    def skill_supports(self, skill_name: str, capability: SkillCapability) -> bool:
        return self._runtime.skills.supports(skill_name, capability)

    async def render_skill(self, request: SkillRenderRequest) -> RenderedSkill:
        return await self._runtime.skills.render(request)
