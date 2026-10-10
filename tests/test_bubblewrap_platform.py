from types import SimpleNamespace

import pytest

from EvernightAI.core.error.sandbox import SandboxConfigurationError
from EvernightAI.core.schema.sandbox import (
    SandboxCommand,
    SandboxExecutionRequest,
    SandboxPolicy,
)
from EvernightAI.infra.adapters.sandbox import bubblewrap


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["win32", "darwin"])
async def test_bubblewrap_rejects_unsupported_platform_before_opening_mounts(
    platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = bubblewrap.BubblewrapSandboxExecutor(bubblewrap_path="bwrap")
    monkeypatch.setattr(bubblewrap, "sys", SimpleNamespace(platform=platform))
    request = SandboxExecutionRequest(
        request_id="unsupported-platform",
        command=SandboxCommand(command=["python", "--version"]),
        policy=SandboxPolicy(),
    )

    with pytest.raises(SandboxConfigurationError, match="requires Linux"):
        await executor.execute(request)
