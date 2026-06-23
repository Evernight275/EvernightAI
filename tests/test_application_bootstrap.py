from typing import Any, cast

import pytest

from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.application.provider import ProviderApplication
from EvernightAI.application.session import SessionApplication
from EvernightAI.application.skill import SkillApplication
from EvernightAI.application.tool import ToolApplication
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol


def test_interface_bootstrap_wraps_existing_runtime() -> None:
    runtime = create_runtime()

    interface = create_interface(runtime)

    assert isinstance(interface, EvernightInterface)
    assert isinstance(interface, EvernightInterfaceProtocol)
    assert interface.runtime is runtime
    assert isinstance(interface.chat, ChatApplication)
    assert isinstance(interface.providers, ProviderApplication)
    assert isinstance(interface.tools, ToolApplication)
    assert isinstance(interface.agent, AgentApplication)
    assert isinstance(interface.agent_runs, AgentRunApplication)
    assert isinstance(interface.skills, SkillApplication)
    assert isinstance(interface.sessions, SessionApplication)


@pytest.mark.asyncio
async def test_runtime_close_closes_registered_stores() -> None:
    runtime = create_runtime()
    closed: list[str] = []

    cast(Any, runtime.context_register).close = lambda: closed.append("context")
    cast(Any, runtime.memory_register).close = lambda: closed.append("memory")
    cast(Any, runtime.session_register).close = lambda: closed.append("session")

    await runtime.close()

    assert closed == ["context", "memory", "session"]
