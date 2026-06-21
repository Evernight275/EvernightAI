from pathlib import Path

from EvernightAI.cli import main


def test_cli_config_check_prints_summary(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "evernight.toml"
    config_path.write_text(
        """
[provider.main]
name = "Main"
type = "openai"
""".strip(),
        encoding="utf-8",
    )

    exit_code = main(["config", "check", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Config OK" in captured.out
    assert "providers: 1" in captured.out


def test_cli_config_show_prints_redacted_json(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "evernight.toml"
    config_path.write_text(
        """
[provider.main]
name = "Main"
type = "openai"
api_key = "secret-key"
""".strip(),
        encoding="utf-8",
    )

    exit_code = main(["config", "show", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"api_key": "***"' in captured.out
    assert "secret-key" not in captured.out
