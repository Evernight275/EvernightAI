import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from EvernightAI.application.bootstrap import create_interface
from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.interface.cli.commands import (
    check_config,
    list_models,
    list_providers,
    run_chat,
    show_config,
)
from EvernightAI.interface.cli.config import load_config
from EvernightAI.interface.cli.schema import EvernightConfig
from EvernightAI.server import create_app_from_config, create_runtime_from_config


DEFAULT_CONFIG_PATH = Path("evernight.toml")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        output = args.handler(args)
    except EvernightAIError as error:
        print(f"error: {error.error_type}: {error}", file=sys.stderr)
        return 1

    if output:
        print(output)

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evernight")
    parser.set_defaults(handler=_print_help(parser))
    subparsers = parser.add_subparsers(dest="command")

    _add_config_subparser(subparsers)
    _add_provider_subparser(subparsers)
    _add_model_subparser(subparsers)
    _add_chat_subparser(subparsers)
    _add_serve_subparser(subparsers)

    return parser


def _add_config_subparser(subparsers: argparse._SubParsersAction) -> None:
    config_parser = subparsers.add_parser("config")
    config_parser.set_defaults(handler=_print_help(config_parser))
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    check_parser = config_subparsers.add_parser("check")
    check_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    check_parser.set_defaults(handler=_handle_config_check)

    show_parser = config_subparsers.add_parser("show")
    show_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    show_parser.set_defaults(handler=_handle_config_show)


def _add_provider_subparser(subparsers: argparse._SubParsersAction) -> None:
    provider_parser = subparsers.add_parser("provider")
    provider_parser.set_defaults(handler=_print_help(provider_parser))
    provider_subparsers = provider_parser.add_subparsers(dest="provider_command")

    list_parser = provider_subparsers.add_parser("list")
    list_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    list_parser.set_defaults(handler=_handle_provider_list)


def _add_model_subparser(subparsers: argparse._SubParsersAction) -> None:
    model_parser = subparsers.add_parser("model")
    model_parser.set_defaults(handler=_print_help(model_parser))
    model_subparsers = model_parser.add_subparsers(dest="model_command")

    list_parser = model_subparsers.add_parser("list")
    list_parser.add_argument(
        "--provider",
        required=True,
        help="Provider id declared in config.",
    )
    list_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    list_parser.set_defaults(handler=_handle_model_list)


def _add_chat_subparser(subparsers: argparse._SubParsersAction) -> None:
    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument(
        "--provider",
        required=True,
        help="Provider id declared in config.",
    )
    chat_parser.add_argument(
        "--model",
        required=True,
        help="Model id to send to the provider.",
    )
    chat_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    chat_parser.add_argument(
        "prompt",
        help="Prompt text to send.",
    )
    chat_parser.set_defaults(handler=_handle_chat)


def _add_serve_subparser(subparsers: argparse._SubParsersAction) -> None:
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    serve_parser.set_defaults(handler=_handle_serve)


def _print_help(parser: argparse.ArgumentParser) -> Callable[[argparse.Namespace], str]:
    def handler(_args: argparse.Namespace) -> str:
        return parser.format_help().rstrip()

    return handler


def _handle_config_check(args: argparse.Namespace) -> str:
    return check_config(args.config)


def _handle_config_show(args: argparse.Namespace) -> str:
    return show_config(args.config)


def _handle_provider_list(args: argparse.Namespace) -> str:
    return list_providers(load_config(args.config))


def _handle_model_list(args: argparse.Namespace) -> str:
    config = load_config(args.config)
    return list_models(config, args.provider)


def _handle_chat(args: argparse.Namespace) -> str:
    config = load_config(args.config)
    interface = _build_interface(config)

    async def _flow() -> str:
        try:
            return await run_chat(
                interface,
                config,
                provider_id=args.provider,
                model_id=args.model,
                prompt=args.prompt,
            )
        finally:
            await interface.close()

    return asyncio.run(_flow())


def _handle_serve(args: argparse.Namespace) -> str:
    import uvicorn

    config = load_config(args.config)
    app = create_app_from_config(config)
    uvicorn.run(
        app,
        host=config.http.host,
        port=config.http.port,
        reload=config.http.reload,
    )
    return ""


def _build_interface(config: EvernightConfig) -> EvernightInterfaceProtocol:
    runtime = create_runtime_from_config(config)
    return create_interface(runtime)


if __name__ == "__main__":
    raise SystemExit(main())
