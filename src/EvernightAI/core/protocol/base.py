from typing import Protocol


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
