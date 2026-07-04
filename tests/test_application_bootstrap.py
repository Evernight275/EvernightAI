from typing import Any, cast
import sqlite3

import pytest

from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.application.data_analysis import DataAnalysisApplication
from EvernightAI.application.provider import ProviderApplication
from EvernightAI.application.session import SessionApplication
from EvernightAI.application.skill import SkillApplication
from EvernightAI.application.tool import ToolApplication
from EvernightAI.bootstrap.config import create_runtime_from_config
from EvernightAI.bootstrap.interface import create_authorized_interface, create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.data_analysis import (
    DataSort,
    DataSortDirection,
    DataStatisticsRequest,
)
from EvernightAI.interface.cli.config import parse_config


def test_interface_bootstrap_wraps_existing_runtime() -> None:
    runtime = create_runtime()

    interface = create_interface(runtime)

    assert isinstance(interface, EvernightInterface)
    assert isinstance(interface, EvernightInterfaceProtocol)
    assert interface.runtime is runtime
    assert isinstance(interface.chat, ChatApplication)
    assert isinstance(interface.providers, ProviderApplication)
    assert isinstance(interface.tools, ToolApplication)
    assert isinstance(interface.data_analysis, DataAnalysisApplication)
    assert isinstance(interface.agent, AgentApplication)
    assert isinstance(interface.agent_runs, AgentRunApplication)
    assert isinstance(interface.skills, SkillApplication)
    assert isinstance(interface.sessions, SessionApplication)


def test_interface_bootstrap_wraps_authorized_interface() -> None:
    interface = create_interface(create_runtime())

    authorized = create_authorized_interface(
        interface,
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1", permissions=["*"]),
    )

    assert isinstance(authorized, AuthorizedEvernightInterface)
    assert isinstance(authorized, EvernightInterfaceProtocol)
    assert authorized.runtime is interface.runtime


@pytest.mark.asyncio
async def test_runtime_close_closes_registered_stores() -> None:
    runtime = create_runtime()
    closed: list[str] = []

    cast(Any, runtime.context_register).close = lambda: closed.append("context")
    cast(Any, runtime.data_analysis_register).close = lambda: closed.append(
        "data_analysis"
    )
    cast(Any, runtime.memory_register).close = lambda: closed.append("memory")
    cast(Any, runtime.session_register).close = lambda: closed.append("session")

    await runtime.close()

    assert closed == ["context", "data_analysis", "memory", "session"]


@pytest.mark.asyncio
async def test_interface_close_drains_agent_runs_before_runtime_close() -> None:
    runtime = create_runtime()
    interface = create_interface(runtime)
    closed: list[str] = []

    async def close_agent_runs() -> None:
        closed.append("agent_runs")

    async def close_runtime() -> None:
        closed.append("runtime")

    cast(Any, interface.agent_runs).close = close_agent_runs
    cast(Any, interface.runtime).close = close_runtime

    await interface.close()

    assert closed == ["agent_runs", "runtime"]


@pytest.mark.asyncio
async def test_configured_sqlite_data_sources_register_with_runtime(tmp_path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE orders (status TEXT NOT NULL, amount REAL NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO orders (status, amount) VALUES (?, ?)",
        [("paid", 30), ("paid", 12), ("refunded", 5)],
    )
    connection.commit()
    connection.close()
    config = parse_config(
        {
            "runtime": {"database_path": str(database_path)},
            "data_analysis": {
                "sqlite_source": {
                    "orders": {
                        "name": "Orders",
                        "table": "orders",
                        "field": {
                            "status": {"field_type": "string"},
                            "amount": {"field_type": "number"},
                        },
                        "metric": {
                            "order_count": {"aggregation": "count"},
                            "revenue": {
                                "aggregation": "sum",
                                "field_id": "amount",
                            },
                        },
                    }
                }
            },
        }
    )
    runtime = create_runtime_from_config(config)

    result = await runtime.data_analysis.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count", "revenue"],
            dimensions=["status"],
            sorts=[DataSort(field_id="revenue", direction=DataSortDirection.DESC)],
        )
    )

    await runtime.close()
    assert [source.source_id for source in runtime.data_analysis.list_sources()] == [
        "orders"
    ]
    assert result.rows[0].dimensions == {"status": "paid"}
    assert result.rows[0].metrics == {"order_count": 2, "revenue": 42.0}
