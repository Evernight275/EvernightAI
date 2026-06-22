from EvernightAI.core.error.skill import (
    SkillExecutionError,
    SkillInputError,
    SkillNotFoundError,
)
from EvernightAI.core.protocol.skill import (
    SkillExecutorProtocol,
    SkillManageProtocol,
    SkillRegisterProtocol,
)
from EvernightAI.core.schema.skill import (
    SkillCall,
    SkillCapability,
    SkillDefinition,
    SkillResult,
)


class SkillRegister(SkillRegisterProtocol):
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._executors: dict[str, SkillExecutorProtocol] = {}

    def register(
        self,
        skill: SkillDefinition,
        executor: SkillExecutorProtocol,
    ) -> None:
        """注册技能"""
        self._skills[skill.name] = skill
        self._executors[skill.name] = executor

    def unregister(self, skill_name: str) -> None:
        """注销技能"""
        if not self.has(skill_name):
            raise SkillNotFoundError(f"The skill {skill_name} is not registered")
        self._skills.pop(skill_name, None)
        self._executors.pop(skill_name, None)

    def get(self, skill_name: str) -> SkillDefinition:
        """获取技能定义"""
        if self.has(skill_name):
            return self._skills[skill_name]
        raise SkillNotFoundError(f"The skill {skill_name} is not found")

    def get_executor(self, skill_name: str) -> SkillExecutorProtocol:
        """获取技能执行器"""
        if self.has(skill_name):
            return self._executors[skill_name]
        raise SkillNotFoundError(f"The skill {skill_name} is not registered")

    def has(self, skill_name: str) -> bool:
        """检查技能是否存在"""
        return skill_name in self._skills and skill_name in self._executors

    def list_skills(self) -> list[SkillDefinition]:
        """列出所有技能定义"""
        return list(self._skills.values())


class SkillManager(SkillManageProtocol):
    def __init__(self, register: SkillRegisterProtocol) -> None:
        self._register = register

    def list_skills(self) -> list[SkillDefinition]:
        """列出所有技能定义"""
        return self._register.list_skills()

    def get_skill(self, skill_name: str) -> SkillDefinition:
        """获取技能定义"""
        return self._register.get(skill_name)

    def supports(self, skill_name: str, capability: SkillCapability) -> bool:
        """检查技能能力"""
        skill = self._register.get(skill_name)
        return capability in skill.capabilities

    async def execute(self, call: SkillCall) -> SkillResult:
        """执行技能调用"""
        if not call.skill_name:
            raise SkillInputError("The skill call must include a skill name")

        skill = self._register.get(call.skill_name)
        executor = self._register.get_executor(skill.name)

        try:
            return await executor(call)
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                f"The skill {skill.name} execution failed", cause=exc
            ) from exc
