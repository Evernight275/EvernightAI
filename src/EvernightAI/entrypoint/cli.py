import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from EvernightAI.bootstrap.config import create_interface_from_config
from EvernightAI.bootstrap.http import create_app_from_config
from EvernightAI.core.error.base import ConfigurationError, EvernightAIError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.interface.cli.commands import (
    SkillCapability,
    check_config,
    list_models,
    list_providers,
    list_skills,
    render_skill,
    run_chat,
    show_skill,
    show_config,
    skill_supports,
)
from EvernightAI.interface.cli.config import load_config
from EvernightAI.interface.cli.schema import EvernightConfig


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
    _add_skill_subparser(subparsers)
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


def _add_skill_subparser(subparsers: argparse._SubParsersAction) -> None:
    skill_parser = subparsers.add_parser("skill")
    skill_parser.set_defaults(handler=_print_help(skill_parser))
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command")

    list_parser = skill_subparsers.add_parser("list")
    list_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    list_parser.set_defaults(handler=_handle_skill_list)

    show_parser = skill_subparsers.add_parser("show")
    show_parser.add_argument("skill_name", help="Registered skill name.")
    show_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    show_parser.set_defaults(handler=_handle_skill_show)

    supports_parser = skill_subparsers.add_parser("supports")
    supports_parser.add_argument("skill_name", help="Registered skill name.")
    supports_parser.add_argument(
        "--capability",
        required=True,
        type=SkillCapability,
        choices=list(SkillCapability),
        help="Skill capability to check.",
    )
    supports_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    supports_parser.set_defaults(handler=_handle_skill_supports)

    render_parser = skill_subparsers.add_parser("render")
    render_parser.add_argument("skill_name", help="Registered skill name.")
    render_parser.add_argument(
        "--render-id",
        default=None,
        help="Render id to use. Defaults to '<skill>-0'.",
    )
    render_parser.add_argument(
        "--vars-json",
        default="{}",
        help="JSON object with render variables.",
    )
    render_parser.add_argument(
        "--metadata-json",
        default="{}",
        help="JSON object with render metadata.",
    )
    render_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    render_parser.set_defaults(handler=_handle_skill_render)


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


def _handle_skill_list(args: argparse.Namespace) -> str:
    return _run_interface_command(args.config, list_skills)


def _handle_skill_show(args: argparse.Namespace) -> str:
    return _run_interface_command(
        args.config,
        lambda interface: show_skill(interface, args.skill_name),
    )


def _handle_skill_supports(args: argparse.Namespace) -> str:
    return _run_interface_command(
        args.config,
        lambda interface: skill_supports(
            interface,
            args.skill_name,
            args.capability,
        ),
    )


def _handle_skill_render(args: argparse.Namespace) -> str:
    async def _flow(interface: EvernightInterfaceProtocol) -> str:
        return await render_skill(
            interface,
            skill_name=args.skill_name,
            render_id=args.render_id or f"{args.skill_name}-0",
            variables=_json_object(args.vars_json),
            metadata=_json_object(args.metadata_json),
        )

    return _run_async_interface_command(args.config, _flow)


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
    return create_interface_from_config(config)


def _run_interface_command(
    config_path: str,
    command: Callable[[EvernightInterfaceProtocol], str],
) -> str:
    async def _flow() -> str:
        interface = _build_interface(load_config(config_path))
        try:
            return command(interface)
        finally:
            await interface.close()

    return asyncio.run(_flow())


def _run_async_interface_command(
    config_path: str,
    command: Callable[[EvernightInterfaceProtocol], object],
) -> str:
    async def _flow() -> str:
        interface = _build_interface(load_config(config_path))
        try:
            result = command(interface)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        finally:
            await interface.close()

    return asyncio.run(_flow())


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("Expected a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ConfigurationError("Expected a JSON object")

    return {
        key: item
        for key, item in parsed.items()
        if isinstance(key, str)
    }


if __name__ == "__main__":
    raise SystemExit(main())
