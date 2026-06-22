from collections.abc import Sequence

from EvernightAI.entrypoint.cli import main as _main


def main(argv: Sequence[str] | None = None) -> int:
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
