import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from EvernightAI.bootstrap.http import create_app_from_config
from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.interface.cli.config import load_config


DEFAULT_CONFIG_PATH = Path("config.toml")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        serve(args.config)
    except EvernightAIError as error:
        print(f"error: {error.error_type}: {error}", file=sys.stderr)
        return 1

    return 0


def serve(config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    config = load_config(config_path)
    app = create_app_from_config(config)
    uvicorn.run(
        app,
        host=config.http.host,
        port=config.http.port,
        reload=config.http.reload,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evernight-http")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the EvernightAI TOML config file.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
