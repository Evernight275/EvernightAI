from collections.abc import Awaitable, Callable

from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillRenderRequest,
    SkillCapability,
    SkillDefinition,
)


SkillRendererProtocol = Callable[[SkillRenderRequest], Awaitable[RenderedSkill]]


class SkillProtocol(EvernightAIProtocol):
    """
    技能协议
    """

    ...


class SkillRenderProtocol(SkillProtocol, ResponsibilityProtocol):
    """
    技能渲染协议
    """

    async def render(self, request: SkillRenderRequest) -> RenderedSkill: ...


class SkillManageProtocol(SkillProtocol, ManageProtocol):
    """
    技能管理协议
    """

    def list_skills(self) -> list[SkillDefinition]: ...

    def get_skill(self, skill_name: str) -> SkillDefinition: ...

    def supports(self, skill_name: str, capability: SkillCapability) -> bool: ...

    async def render(self, request: SkillRenderRequest) -> RenderedSkill: ...


class SkillRegisterProtocol(SkillProtocol, RegisterProtocol):
    """
    技能注册协议
    """

    def register(
        self,
        skill: SkillDefinition,
        renderer: SkillRendererProtocol,
    ) -> None: ...

    def unregister(self, skill_name: str) -> None: ...

    def get(self, skill_name: str) -> SkillDefinition: ...

    def get_renderer(self, skill_name: str) -> SkillRendererProtocol: ...

    def has(self, skill_name: str) -> bool: ...

    def list_skills(self) -> list[SkillDefinition]: ...
