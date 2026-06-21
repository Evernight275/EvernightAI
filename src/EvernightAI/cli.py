import argparse
from collections.abc import Sequence
from pathlib import Path

from EvernightAI.interface.cli.commands import check_config, show_config


DEFAULT_CONFIG_PATH = Path("evernight.toml")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    output = args.handler(args)
    if output:
        print(output)

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evernight")
    parser.set_defaults(handler=_print_help(parser))
    subparsers = parser.add_subparsers(dest="command")

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

    return parser


def _print_help(parser: argparse.ArgumentParser):
    def handler(_args: argparse.Namespace) -> str:
        return parser.format_help().rstrip()

    return handler


def _handle_config_check(args: argparse.Namespace) -> str:
    return check_config(args.config)


def _handle_config_show(args: argparse.Namespace) -> str:
    return show_config(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
