"""Probe configured providers without changing the application's database."""

import argparse
import ast
import asyncio
import json
import random
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.core.error.provider import ProviderUnavailableError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import ProviderConfig, ProviderModelCapability
from EvernightAI.core.schema.stream import ChatStreamEventType
from EvernightAI.interface.cli.config import load_config


def emit(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=True), flush=True)


async def probe_call(
    interface: EvernightInterfaceProtocol,
    provider_id: str,
    model_id: str,
    *,
    declared: bool,
    streaming: bool,
    timeout: float,
) -> dict[str, Any]:
    request = ChatRequest(
        model_id=model_id,
        messages=[Content(role=MessageRole.USER, content=[
            ContentPart(type=ContentPartType.TEXT, text="Reply with only OK."),
        ])],
        metadata={"timeout_seconds": timeout},
    )
    before = request.model_dump(mode="json")
    result: dict[str, Any] = {
        "provider": provider_id,
        "model": model_id,
        "case": ("declared" if declared else "undeclared")
        + ("_stream" if streaming else "_chat"),
    }
    started = perf_counter()
    text = ""
    try:
        async with asyncio.timeout(timeout):
            if streaming:
                done = False
                stream = await interface.chat.chat_stream(provider_id, request)
                async for event in stream:
                    if event.event_type is ChatStreamEventType.ERROR:
                        result["error_type"] = event.error_type or "StreamError"
                        break
                    if event.event_type is ChatStreamEventType.MESSAGE_DELTA:
                        text += event.text_delta or ""
                    if event.event_type is ChatStreamEventType.DONE:
                        done = True
                result["done"] = done
                result["success"] = done and bool(text.strip())
            else:
                response = await interface.chat.chat(provider_id, request)
                text = "".join(part.text or "" for part in response.message.content or [])
                result["success"] = bool(text.strip())
    except ProviderUnavailableError as error:
        result.update(success=False, skipped=True, error_type=error.error_type)
    except EvernightAIError as error:
        result.update(success=False, error_type=error.error_type)
        result["upstream_status"] = getattr(error.cause, "status_code", None)
    except TimeoutError:
        result.update(success=False, error_type="ProbeTimeout")
    except Exception as error:
        result.update(success=False, error_type=type(error).__name__)
    result["request_unchanged"] = before == request.model_dump(mode="json")
    if not result["request_unchanged"]:
        result.update(success=False, error_type="RequestMutation")
    result["output_chars"] = len(text)
    result["elapsed_ms"] = round((perf_counter() - started) * 1000, 1)
    emit(result)
    return result


async def probe_provider(
    config: ProviderConfig, model_id: str, timeout: float,
) -> list[dict[str, Any]]:
    runtime = create_runtime()
    interface = create_interface(runtime)
    results: list[dict[str, Any]] = []
    try:
        await runtime.initialize()
        for declared in (True, False):
            candidate = config.model_copy(deep=True)
            # Disable discovery so undeclared requests cannot depend on /models.
            candidate.discover_models = False
            if not declared:
                candidate.model = {}
            await interface.providers.create_provider(candidate)
            results.extend(await asyncio.gather(*(
                probe_call(
                    interface, config.provider_id, model_id,
                    declared=declared, streaming=streaming, timeout=timeout,
                )
                for streaming in (False, True)
            )))
            await interface.providers.delete_provider(config.provider_id)
    except EvernightAIError as error:
        result = {"provider": config.provider_id, "case": "setup",
                  "success": False, "error_type": error.error_type}
        emit(result)
        results.append(result)
    finally:
        await interface.close()
    return results


async def probe_pasted_retry(source_path: Path) -> list[dict[str, Any]]:
    """Execute only the pasted retry methods with local fake dependencies."""
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == "ProviderOpenAIOfficial")
    methods = [node for node in original.body if isinstance(node, ast.AsyncFunctionDef)
               and node.name in {"text_chat", "text_chat_stream"}]
    if len(methods) != 2:
        raise ValueError("Expected both retry methods in the pasted source")
    body: list[ast.stmt] = [
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        ast.ClassDef(name=original.name, bases=[], keywords=[], body=methods,
                     decorator_list=[], type_params=[]),
    ]
    extracted = ast.Module(body=body, type_ignores=[])
    namespace: dict[str, Any] = {
        "random": random,
        "logger": SimpleNamespace(error=lambda *args: None),
    }
    exec(compile(ast.fix_missing_locations(extracted), str(source_path), "exec"), namespace)
    provider = namespace[original.name]()
    provider.api_keys = ["local-fake-key"]
    provider.client = SimpleNamespace(api_key=None)
    calls = 0
    output: list[str] = []

    async def prepare(*args, **kwargs):
        return {}, []

    async def query(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 10:
            raise RuntimeError("local-retryable-error")
        return "OK"

    async def query_stream(*args, **kwargs):
        yield await query()

    async def handle(error, payload, contexts, tools, key, keys, *args, **kwargs):
        return False, key, keys, payload, contexts, tools, False

    provider._prepare_chat_payload = prepare
    provider._query = query
    provider._query_stream = query_stream
    provider._handle_api_error = handle
    results = []
    for streaming in (False, True):
        calls = 0
        output = []
        error_type = None
        try:
            if streaming:
                async for part in provider.text_chat_stream():
                    output.append(part)
            else:
                output.append(await provider.text_chat())
        except Exception as error:
            error_type = type(error).__name__
        result = {"implementation": "pasted_retry_methods",
                  "case": "last_attempt_success_stream" if streaming else "last_attempt_success_chat",
                  "calls": calls, "last_call_succeeded": calls == 10,
                  "delivered_output": bool(output), "error_type": error_type,
                  "bug_reproduced": calls == 10 and error_type is not None}
        emit(result)
        results.append(result)
    return results


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    results: list[dict[str, Any]] = []
    if args.comparison_source:
        results.extend(await probe_pasted_retry(args.comparison_source))
    providers = [p for p in config.providers if not args.provider or p.provider_id in args.provider]
    if not providers:
        raise ValueError("No matching configured providers")
    for provider in providers:
        models = [m for m in provider.model.values()
                  if not m.capabilities or ProviderModelCapability.CHAT in m.capabilities]
        model_id = args.model or (models[0].model_id if models else None)
        if not provider.is_enabled or model_id is None:
            result = {"provider": provider.provider_id, "skipped": True,
                      "reason": "disabled" if not provider.is_enabled else "no declared chat model; use --model"}
            emit(result)
            results.append(result)
            continue
        emit({"provider": provider.provider_id, "type": provider.type.value,
              "model": model_id, "starting": True})
        results.extend(await probe_provider(provider, model_id, args.timeout))
    report = {"config": str(args.config.resolve()), "results": results}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    failures = [r for r in results if r.get("success") is False and not r.get("skipped")]
    emit({"finished": True, "failed_cases": len(failures)})
    return int(bool(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--provider", action="append")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--comparison-source", type=Path)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        return asyncio.run(run(args))
    except (EvernightAIError, ValueError, OSError) as error:
        emit({"failed": True, "error_type": type(error).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
