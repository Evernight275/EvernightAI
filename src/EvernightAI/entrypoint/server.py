import argparse
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from EvernightAI.bootstrap.http import create_app_from_config
from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.interface.cli.config import load_config
from EvernightAI.interface.cli.logging import configure_logging, uvicorn_log_config

DEFAULT_CONFIG_PATH = Path("config.toml")

LOGO = """
      :::::::::: :::     ::: :::::::::: :::::::::  ::::    ::: ::::::::::: ::::::::  :::    ::: :::::::::::
     :+:        :+:     :+: :+:        :+:    :+: :+:+:   :+:     :+:    :+:    :+: :+:    :+:     :+:
    +:+        +:+     +:+ +:+        +:+    +:+ :+:+:+  +:+     +:+    +:+        +:+    +:+     +:+
   +#++:++#   +#+     +:+ +#++:++#   +#++:++#:  +#+ +:+ +#+     +#+    :#:        +#++:++#++     +#+
  +#+         +#+   +#+  +#+        +#+    +#+ +#+  +#+#+#     +#+    +#+   +#+# +#+    +#+     +#+
 #+#          #+#+#+#   #+#        #+#    #+# #+#   #+#+#     #+#    #+#    #+# #+#    #+#     #+#
##########     ###     ########## ###    ### ###    #### ########### ########  ###    ###     ###
"""


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
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
    for line in _startup_info_lines(
        config_path,
        host=config.http.host,
        port=config.http.port,
        color=sys.stdout.isatty(),
    ):
        print(line)
    uvicorn.run(
        app,
        host=config.http.host,
        port=config.http.port,
        reload=config.http.reload,
        log_config=uvicorn_log_config(),
        server_header=False,
    )


def _startup_info_lines(
    config_path: str | Path,
    *,
    host: str,
    port: int,
    color: bool = False,
) -> list[str]:
    return [
        "\033[2J\033[H",
        _ansi(LOGO, "1;3;36", color),
        _ansi("-" * 75, "2", color),
        f"{_ansi('System：', '1;36', color)}  {_ansi(platform.system() + ' ' + platform.release(), '97', color)} ({_ansi(platform.machine(), '97', color)})",
        f"{_ansi('Python：', '1;36', color)}  {_ansi(platform.python_version(), '97', color)}",
        f"{_ansi('Config：', '1;36', color)}  {_ansi(str(config_path), '97', color)}",
        f"{_ansi('HTTP：', '1;36', color)}    {_ansi(f'http://{host}:{port}', '97', color)}",
        _ansi("-" * 75, "2", color),
        f"{_ansi('                                  ', '1;32', color)}",
    ]


def _ansi(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text

    return f"\033[{code}m{text}\033[0m"


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
