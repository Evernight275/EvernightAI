import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from EvernightAI.bootstrap.config import create_interface_from_config
from EvernightAI.core.error.base import ConfigurationError, EvernightAIError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.entrypoint.server import serve as serve_http
from EvernightAI.interface.cli.commands import (
    SkillCapability,
    append_context_message,
    archive_session,
    check_config,
    chat_with_session,
    create_context,
    create_memory,
    create_session,
    delete_context,
    delete_memory,
    delete_session,
    get_agent_run,
    get_context,
    get_memory,
    get_session,
    list_agent_runs,
    list_agent_trace,
    list_contexts,
    list_memories,
    list_models,
    list_providers,
    list_sessions,
    list_skills,
    render_skill,
    replace_context,
    replace_session,
    approve_pending_agent_run,
    resume_agent_run,
    run_chat,
    select_memories,
    show_skill,
    show_config,
    start_agent_run,
    start_session_agent_run,
    skill_supports,
)
from EvernightAI.interface.cli.config import load_config
from EvernightAI.interface.cli.schema import EvernightConfig


DEFAULT_CONFIG_PATH = Path("config.toml")


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
    _add_context_subparser(subparsers)
    _add_memory_subparser(subparsers)
    _add_session_subparser(subparsers)
    _add_agent_run_subparser(subparsers)
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


def _add_context_subparser(subparsers: argparse._SubParsersAction) -> None:
    context_parser = subparsers.add_parser("context")
    context_parser.set_defaults(handler=_print_help(context_parser))
    context_subparsers = context_parser.add_subparsers(dest="context_command")

    list_parser = context_subparsers.add_parser("list")
    _add_config_argument(list_parser)
    list_parser.set_defaults(handler=_handle_context_list)

    get_parser = context_subparsers.add_parser("get")
    get_parser.add_argument("context_id")
    _add_config_argument(get_parser)
    get_parser.set_defaults(handler=_handle_context_get)

    create_parser = context_subparsers.add_parser("create")
    create_parser.add_argument("--json", required=True, help="Context JSON object.")
    _add_config_argument(create_parser)
    create_parser.set_defaults(handler=_handle_context_create)

    append_parser = context_subparsers.add_parser("append")
    append_parser.add_argument("context_id")
    append_parser.add_argument(
        "--message-json",
        required=True,
        help="Content JSON object to append.",
    )
    _add_config_argument(append_parser)
    append_parser.set_defaults(handler=_handle_context_append)

    replace_parser = context_subparsers.add_parser("replace")
    replace_parser.add_argument("context_id")
    replace_parser.add_argument("--json", required=True, help="Context JSON object.")
    _add_config_argument(replace_parser)
    replace_parser.set_defaults(handler=_handle_context_replace)

    delete_parser = context_subparsers.add_parser("delete")
    delete_parser.add_argument("context_id")
    _add_config_argument(delete_parser)
    delete_parser.set_defaults(handler=_handle_context_delete)


def _add_memory_subparser(subparsers: argparse._SubParsersAction) -> None:
    memory_parser = subparsers.add_parser("memory")
    memory_parser.set_defaults(handler=_print_help(memory_parser))
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command")

    list_parser = memory_subparsers.add_parser("list")
    _add_config_argument(list_parser)
    list_parser.set_defaults(handler=_handle_memory_list)

    get_parser = memory_subparsers.add_parser("get")
    get_parser.add_argument("memory_id")
    _add_config_argument(get_parser)
    get_parser.set_defaults(handler=_handle_memory_get)

    create_parser = memory_subparsers.add_parser("create")
    create_parser.add_argument("--json", required=True, help="Memory JSON object.")
    _add_config_argument(create_parser)
    create_parser.set_defaults(handler=_handle_memory_create)

    select_parser = memory_subparsers.add_parser("select")
    select_parser.add_argument(
        "--query-json",
        default=None,
        help="Optional memory query JSON object.",
    )
    _add_config_argument(select_parser)
    select_parser.set_defaults(handler=_handle_memory_select)

    delete_parser = memory_subparsers.add_parser("delete")
    delete_parser.add_argument("memory_id")
    _add_config_argument(delete_parser)
    delete_parser.set_defaults(handler=_handle_memory_delete)


def _add_session_subparser(subparsers: argparse._SubParsersAction) -> None:
    session_parser = subparsers.add_parser("session")
    session_parser.set_defaults(handler=_print_help(session_parser))
    session_subparsers = session_parser.add_subparsers(dest="session_command")

    list_parser = session_subparsers.add_parser("list")
    _add_config_argument(list_parser)
    list_parser.set_defaults(handler=_handle_session_list)

    get_parser = session_subparsers.add_parser("get")
    get_parser.add_argument("session_id")
    _add_config_argument(get_parser)
    get_parser.set_defaults(handler=_handle_session_get)

    create_parser = session_subparsers.add_parser("create")
    create_parser.add_argument("--json", required=True, help="Session JSON object.")
    _add_config_argument(create_parser)
    create_parser.set_defaults(handler=_handle_session_create)

    replace_parser = session_subparsers.add_parser("replace")
    replace_parser.add_argument("session_id")
    replace_parser.add_argument("--json", required=True, help="Session JSON object.")
    _add_config_argument(replace_parser)
    replace_parser.set_defaults(handler=_handle_session_replace)

    archive_parser = session_subparsers.add_parser("archive")
    archive_parser.add_argument("session_id")
    _add_config_argument(archive_parser)
    archive_parser.set_defaults(handler=_handle_session_archive)

    delete_parser = session_subparsers.add_parser("delete")
    delete_parser.add_argument("session_id")
    _add_config_argument(delete_parser)
    delete_parser.set_defaults(handler=_handle_session_delete)

    chat_parser = session_subparsers.add_parser("chat")
    chat_parser.add_argument("session_id")
    chat_parser.add_argument(
        "--request-json",
        required=True,
        help="SessionChatRequest JSON object.",
    )
    _add_config_argument(chat_parser)
    chat_parser.set_defaults(handler=_handle_session_chat)

    agent_run_parser = session_subparsers.add_parser("agent-run")
    agent_run_parser.add_argument("session_id")
    agent_run_parser.add_argument(
        "--request-json",
        required=True,
        help="SessionAgentRunRequest JSON object.",
    )
    _add_config_argument(agent_run_parser)
    agent_run_parser.set_defaults(handler=_handle_session_agent_run)


def _add_agent_run_subparser(subparsers: argparse._SubParsersAction) -> None:
    agent_run_parser = subparsers.add_parser("agent-run")
    agent_run_parser.set_defaults(handler=_print_help(agent_run_parser))
    agent_run_subparsers = agent_run_parser.add_subparsers(dest="agent_run_command")

    list_parser = agent_run_subparsers.add_parser("list")
    _add_config_argument(list_parser)
    list_parser.set_defaults(handler=_handle_agent_run_list)

    get_parser = agent_run_subparsers.add_parser("get")
    get_parser.add_argument("run_id")
    _add_config_argument(get_parser)
    get_parser.set_defaults(handler=_handle_agent_run_get)

    trace_parser = agent_run_subparsers.add_parser("trace")
    trace_parser.add_argument("run_id")
    _add_config_argument(trace_parser)
    trace_parser.set_defaults(handler=_handle_agent_run_trace)

    start_parser = agent_run_subparsers.add_parser("start")
    start_parser.add_argument(
        "--request-json",
        required=True,
        help="AgentRunRequest JSON object.",
    )
    _add_config_argument(start_parser)
    start_parser.set_defaults(handler=_handle_agent_run_start)

    resume_parser = agent_run_subparsers.add_parser("resume")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument(
        "--approvals-json",
        required=True,
        help="JSON array of ToolApprovalDecision objects.",
    )
    _add_config_argument(resume_parser)
    resume_parser.set_defaults(handler=_handle_agent_run_resume)

    approve_parser = agent_run_subparsers.add_parser("approve")
    approve_parser.add_argument("run_id")
    _add_config_argument(approve_parser)
    approve_parser.set_defaults(handler=_handle_agent_run_approve)


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


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )


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


def _handle_context_list(args: argparse.Namespace) -> str:
    return _run_async_interface_command(args.config, list_contexts)


def _handle_context_get(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: get_context(interface, args.context_id),
    )


def _handle_context_create(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: create_context(interface, args.json),
    )


def _handle_context_append(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: append_context_message(
            interface,
            args.context_id,
            args.message_json,
        ),
    )


def _handle_context_replace(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: replace_context(interface, args.context_id, args.json),
    )


def _handle_context_delete(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: delete_context(interface, args.context_id),
    )


def _handle_memory_list(args: argparse.Namespace) -> str:
    return _run_async_interface_command(args.config, list_memories)


def _handle_memory_get(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: get_memory(interface, args.memory_id),
    )


def _handle_memory_create(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: create_memory(interface, args.json),
    )


def _handle_memory_select(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: select_memories(interface, args.query_json),
    )


def _handle_memory_delete(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: delete_memory(interface, args.memory_id),
    )


def _handle_session_list(args: argparse.Namespace) -> str:
    return _run_async_interface_command(args.config, list_sessions)


def _handle_session_get(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: get_session(interface, args.session_id),
    )


def _handle_session_create(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: create_session(interface, args.json),
    )


def _handle_session_replace(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: replace_session(interface, args.session_id, args.json),
    )


def _handle_session_archive(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: archive_session(interface, args.session_id),
    )


def _handle_session_delete(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: delete_session(interface, args.session_id),
    )


def _handle_session_chat(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: chat_with_session(
            interface,
            args.session_id,
            args.request_json,
        ),
    )


def _handle_session_agent_run(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: start_session_agent_run(
            interface,
            args.session_id,
            args.request_json,
        ),
    )


def _handle_agent_run_list(args: argparse.Namespace) -> str:
    return _run_interface_command(args.config, list_agent_runs)


def _handle_agent_run_get(args: argparse.Namespace) -> str:
    return _run_interface_command(
        args.config,
        lambda interface: get_agent_run(interface, args.run_id),
    )


def _handle_agent_run_trace(args: argparse.Namespace) -> str:
    return _run_interface_command(
        args.config,
        lambda interface: list_agent_trace(interface, args.run_id),
    )


def _handle_agent_run_start(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: start_agent_run(interface, args.request_json),
    )


def _handle_agent_run_resume(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: resume_agent_run(
            interface,
            args.run_id,
            args.approvals_json,
        ),
    )


def _handle_agent_run_approve(args: argparse.Namespace) -> str:
    return _run_async_interface_command(
        args.config,
        lambda interface: approve_pending_agent_run(interface, args.run_id),
    )


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
    serve_http(args.config)
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
