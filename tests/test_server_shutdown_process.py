import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from EvernightAI.infra.adapters.agent.sqlite import SQLiteAgentRunStateRegister


SERVER_SCRIPT = """
import asyncio
import sys
from pathlib import Path
import uvicorn
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.schema.context import Context
from EvernightAI.interface.http.app import create_http_app
from tests.test_provider_domain import FakeProvider
from tests.test_application_agent import make_config

database, marker, port, ending = sys.argv[1:]
class WaitingProvider(FakeProvider):
    async def chat_stream(self, request):
        Path(marker).write_text('opening', encoding='utf-8')
        await asyncio.sleep(0.5 if ending == 'complete' else 10)
        return await super().chat_stream(request)
    async def close(self):
        await super().close()
        Path(marker + '.closed').write_text('closed', encoding='utf-8')

async def main():
    runtime = create_sqlite_runtime(database)
    async def build_provider(config):
        return WaitingProvider()
    runtime.provider_factory.register(make_config().type, build_provider)
    await runtime.providers.create(make_config())
    await runtime.contexts.create(Context(context_id='shutdown-test'))
    app = create_http_app(create_interface(runtime))
    await uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=int(port), log_level='info')).serve()

asyncio.run(main())
"""


@pytest.mark.skipif(
    os.name == "nt", reason="Ctrl+C process acceptance uses POSIX SIGINT"
)
@pytest.mark.parametrize("ending", ["complete", "timeout"])
def test_ctrl_c_during_stream_opening_closes_server_and_persists_state(
    tmp_path: Path, ending: str
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    database = tmp_path / "runtime.sqlite3"
    marker = tmp_path / "opening"
    with (tmp_path / "server.log").open("w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SERVER_SCRIPT,
                str(database),
                str(marker),
                str(port),
                ending,
            ],
            cwd=Path(__file__).resolve().parents[1],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        if client.get("/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert process.poll() is None, "Server exited before startup"
                    assert time.monotonic() < deadline, "Server failed to start"
                    time.sleep(0.02)
                with client.stream(
                    "POST",
                    "/agent-runs/stream",
                    json={
                        "provider_id": "provider-1",
                        "model_id": "model-1",
                        "context_id": "shutdown-test",
                        "messages": [
                            {
                                "role": "user",
                                "content": [{"type": "text", "text": "Wait"}],
                            }
                        ],
                        "timeout_seconds": 0.5 if ending == "timeout" else 5,
                        "metadata": {"run_id": "ctrl-c-test", "stream": True},
                    },
                ) as response:
                    assert response.status_code == 200
                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            break
                    deadline = time.monotonic() + 2
                    while not marker.exists():
                        assert time.monotonic() < deadline, "Provider did not start"
                        time.sleep(0.01)
                    process.send_signal(signal.SIGINT)
                    # Disconnect while the producer is still waiting for the provider.
                process.wait(timeout=5)
            log.seek(0)
            output = log.read()
            assert "Application shutdown complete" in output, output
            assert Path(str(marker) + ".closed").exists(), output
            states = SQLiteAgentRunStateRegister(database)
            try:
                state = states.get_state("ctrl-c-test")
                assert state.status.value in (
                    {"finished"} if ending == "complete" else {"failed", "paused"}
                )
            finally:
                states.close()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
