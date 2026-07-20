from EvernightAI.core.error.skill import (
    SkillInputError,
    SkillNotFoundError,
    SkillRenderError,
)
from EvernightAI.core.protocol.skill import (
    SkillManageProtocol,
    SkillRegisterProtocol,
    SkillRendererProtocol,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)


class SkillRegister(SkillRegisterProtocol):
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._renderers: dict[str, SkillRendererProtocol] = {}

    def register(
        self,
        skill: SkillDefinition,
        renderer: SkillRendererProtocol,
    ) -> None:
        self._skills[skill.name] = skill
        self._renderers[skill.name] = renderer

    def unregister(self, skill_name: str) -> None:
        if not self.has(skill_name):
            raise SkillNotFoundError(f"The skill {skill_name} is not registered")
        self._skills.pop(skill_name, None)
        self._renderers.pop(skill_name, None)

    def get(self, skill_name: str) -> SkillDefinition:
        if self.has(skill_name):
            return self._skills[skill_name]
        raise SkillNotFoundError(f"The skill {skill_name} is not found")

    def get_renderer(self, skill_name: str) -> SkillRendererProtocol:
        if self.has(skill_name):
            return self._renderers[skill_name]
        raise SkillNotFoundError(f"The skill {skill_name} is not registered")

    def has(self, skill_name: str) -> bool:
        return skill_name in self._skills and skill_name in self._renderers

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())


class SkillManager(SkillManageProtocol):
    def __init__(self, register: SkillRegisterProtocol) -> None:
        self._register = register

    def list_skills(self) -> list[SkillDefinition]:
        return self._register.list_skills()

    def get_skill(self, skill_name: str) -> SkillDefinition:
        return self._register.get(skill_name)

    def supports(self, skill_name: str, capability: SkillCapability) -> bool:
        skill = self._register.get(skill_name)
        return capability in skill.capabilities

    async def render(self, request: SkillRenderRequest) -> RenderedSkill:
        if not request.skill_name:
            raise SkillInputError("The skill render request must include a skill name")

        skill = self._register.get(request.skill_name)
        renderer = self._register.get_renderer(skill.name)

        try:
            return await renderer(request)
        except SkillRenderError:
            raise
        except Exception as exc:
            raise SkillRenderError(
                f"The skill {skill.name} render failed", cause=exc
            ) from exc
