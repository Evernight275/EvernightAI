"""Probe configured providers without changing the application's database."""

import argparse
import asyncio
import json
import math
from pathlib import Path
from time import perf_counter
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
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
)
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
        messages=[
            Content(
                role=MessageRole.USER,
                content=[
                    ContentPart(type=ContentPartType.TEXT, text="Reply with only OK."),
                ],
            )
        ],
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
                    if event.event_type is ChatStreamEventType.MESSAGE_DELTA:
                        text += event.text_delta or ""
                    if event.event_type is ChatStreamEventType.DONE:
                        done = True
                result["done"] = done
                result["success"] = (
                    done and bool(text.strip()) and "error_type" not in result
                )
                if not result["success"] and "error_type" not in result:
                    result["error_type"] = "EmptyOutput" if done else "IncompleteStream"
            else:
                response = await interface.chat.chat(provider_id, request)
                text = "".join(
                    part.text or "" for part in response.message.content or []
                )
                result["success"] = bool(text.strip())
                if not result["success"]:
                    result["error_type"] = "EmptyOutput"
    except ProviderUnavailableError as error:
        result.update(
            success=False,
            skipped=True,
            error_type=error.error_type,
            reason="Provider unavailable; success path not verified",
        )
    except EvernightAIError as error:
        result.update(success=False, error_type=error.error_type)
        result["upstream_status"] = getattr(error.cause, "status_code", None)
    except TimeoutError:
        result.update(success=False, error_type="ProbeTimeout")
    except Exception as error:
        result.update(success=False, error_type=type(error).__name__)
    result["request_unchanged"] = before == request.model_dump(mode="json")
    if not result["request_unchanged"]:
        result.update(success=False, skipped=False, error_type="RequestMutation")
    result["output_chars"] = len(text)
    result["elapsed_ms"] = round((perf_counter() - started) * 1000, 1)
    emit(result)
    return result


async def probe_provider(
    config: ProviderConfig,
    model_id: str,
    timeout: float,
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
            if declared:
                if not any(
                    model.model_id == model_id for model in candidate.model.values()
                ):
                    candidate.model[model_id] = ProviderModelConfig(model_id=model_id)
            else:
                candidate.model = {}
            await interface.providers.create_provider(candidate)
            results.extend(
                await asyncio.gather(
                    *(
                        probe_call(
                            interface,
                            config.provider_id,
                            model_id,
                            declared=declared,
                            streaming=streaming,
                            timeout=timeout,
                        )
                        for streaming in (False, True)
                    )
                )
            )
            await interface.providers.delete_provider(config.provider_id)
    except EvernightAIError as error:
        result = {
            "provider": config.provider_id,
            "case": "setup",
            "success": False,
            "error_type": error.error_type,
        }
        emit(result)
        results.append(result)
    finally:
        await interface.close()
    return results


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    results: list[dict[str, Any]] = []
    unknown = set(args.provider or []) - {p.provider_id for p in config.providers}
    if unknown:
        raise ValueError("Unknown provider ID: " + ", ".join(sorted(unknown)))
    providers = [
        p
        for p in config.providers
        if not args.provider or p.provider_id in args.provider
    ]
    if not providers:
        raise ValueError("No matching configured providers")
    for provider in providers:
        models = [
            m
            for m in provider.model.values()
            if not m.capabilities or ProviderModelCapability.CHAT in m.capabilities
        ]
        model_id = args.model or (models[0].model_id if models else None)
        if not provider.is_enabled or model_id is None:
            result = {
                "provider": provider.provider_id,
                "skipped": True,
                "reason": "disabled"
                if not provider.is_enabled
                else "no declared chat model; use --model",
            }
            emit(result)
            results.append(result)
            continue
        emit(
            {
                "provider": provider.provider_id,
                "type": provider.type.value,
                "model": model_id,
                "starting": True,
            }
        )
        results.extend(await probe_provider(provider, model_id, args.timeout))
    passed = sum(r.get("success") is True and not r.get("skipped") for r in results)
    skipped = sum(bool(r.get("skipped")) for r in results)
    failed = len(results) - passed - skipped
    summary = {
        "finished": True,
        "passed_cases": passed,
        "failed_cases": failed,
        "skipped_cases": skipped,
    }
    report = {
        "config": str(args.config.resolve()),
        "results": results,
        "summary": summary,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
    emit(summary)
    if failed:
        return 1
    return 2 if skipped or not passed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument(
        "--provider", action="append", help="Provider ID; repeat to select several"
    )
    parser.add_argument("--model", help="Override the model for a single --provider")
    parser.add_argument(
        "--timeout", type=float, default=45, help="Total seconds per call (default: 45)"
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Save a JSON report without credentials or response text",
    )
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if args.model is not None:
        if len(set(args.provider or [])) != 1 or not args.model.strip():
            parser.error(
                "--model requires exactly one --provider and a nonblank model ID"
            )
        args.model = args.model.strip()
    try:
        return asyncio.run(run(args))
    except ValueError as error:
        emit({"failed": True, "error_type": type(error).__name__, "reason": str(error)})
        return 1
    except (EvernightAIError, OSError) as error:
        emit({"failed": True, "error_type": type(error).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
