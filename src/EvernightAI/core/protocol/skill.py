from collections.abc import Awaitable, Callable

from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
)
from EvernightAI.core.schema.skill import SkillCall, SkillDefinition, SkillResult


SkillExecutorProtocol = Callable[[SkillCall], Awaitable[SkillResult]]


class SkillProtocol(EvernightAIProtocol):
    """
    技能协议
    """

    ...


class SkillExecuteProtocol(SkillProtocol, ResponsibilityProtocol):
    """
    技能执行协议
    """

    async def execute(self, call: SkillCall) -> SkillResult: ...


class SkillManageProtocol(SkillProtocol, ManageProtocol):
    """
    技能管理协议
    """

    def list_skills(self) -> list[SkillDefinition]: ...

    async def execute(self, call: SkillCall) -> SkillResult: ...


class SkillRegisterProtocol(SkillProtocol, RegisterProtocol):
    """
    技能注册协议
    """

    def register(
        self,
        skill: SkillDefinition,
        executor: SkillExecutorProtocol,
    ) -> None: ...

    def unregister(self, skill_name: str) -> None: ...

    def get(self, skill_name: str) -> SkillDefinition: ...

    def get_executor(self, skill_name: str) -> SkillExecutorProtocol: ...

    def has(self, skill_name: str) -> bool: ...

    def list_skills(self) -> list[SkillDefinition]: ...
