from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from EvernightAI.core.protocol.provider import (
        ProviderFactoryProtocol,
        ProviderManageProtocol,
    )
    from EvernightAI.core.protocol.tool import ToolManageProtocol, ToolRegisterProtocol


class EvernightAIProtocol(Protocol):
    """
    EvernightAI 一切协议的基类
    """

    ...


class ResponsibilityProtocol(EvernightAIProtocol):
    """
    职责协议
    """

    ...


class InstanceProtocol(EvernightAIProtocol):
    """
    实例协议
    """

    ...


class RuntimeProtocol(EvernightAIProtocol):
    """
    运行时协议
    """

    @property
    def provider_factory(self) -> ProviderFactoryProtocol: ...

    @property
    def providers(self) -> ProviderManageProtocol: ...

    @property
    def tool_register(self) -> ToolRegisterProtocol: ...

    @property
    def tools(self) -> ToolManageProtocol: ...

    async def close(self) -> None: ...


class RegisterProtocol(ResponsibilityProtocol):
    """
    注册职责协议
    """


class ManageProtocol(ResponsibilityProtocol):
    """
    管理协议
    """


class FactoryProtocol(ResponsibilityProtocol):
    """
    工厂协议
    """
