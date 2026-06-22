import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "EvernightAI.bootstrap.http:create_app",
        factory=True,
        host=os.getenv("EVERNIGHTAI_HTTP_HOST", "127.0.0.1"),
        port=_env_int("EVERNIGHTAI_HTTP_PORT", 8000),
        reload=_env_bool("EVERNIGHTAI_HTTP_RELOAD", False),
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    return int(value)


if __name__ == "__main__":
    main()
