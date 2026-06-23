from pathlib import Path

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.cli import main as package_main
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)
from EvernightAI.entrypoint.cli import main as entrypoint_main


def test_entrypoint_cli_config_check_prints_summary(
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

    exit_code = entrypoint_main(["config", "check", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Config OK" in captured.out
    assert "providers: 1" in captured.out


def test_package_cli_wrapper_prints_redacted_config_json(
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

    exit_code = package_main(["config", "show", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"api_key": "***"' in captured.out
    assert "secret-key" not in captured.out


def test_entrypoint_cli_skill_commands(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    config_path = tmp_path / "evernight.toml"
    config_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.create_interface_from_config",
        lambda _config: create_skill_interface(),
    )

    assert entrypoint_main(["skill", "list", "--config", str(config_path)]) == 0
    list_output = capsys.readouterr().out
    assert "summarize" in list_output

    assert (
        entrypoint_main(
            ["skill", "show", "summarize", "--config", str(config_path)]
        )
        == 0
    )
    show_output = capsys.readouterr().out
    assert '"name": "summarize"' in show_output

    assert (
        entrypoint_main(
            [
                "skill",
                "supports",
                "summarize",
                "--capability",
                "chat",
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    supports_output = capsys.readouterr().out
    assert supports_output.strip() == "yes"

    assert (
        entrypoint_main(
            [
                "skill",
                "render",
                "summarize",
                "--vars-json",
                '{"text": "hello"}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    render_output = capsys.readouterr().out
    assert '"render_id": "summarize-0"' in render_output
    assert '"text": "hello"' in render_output


def create_skill_interface():
    async def summarize(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
            messages=[
                Content(
                    role=MessageRole.SYSTEM,
                    content=[
                        ContentPart(
                            type=ContentPartType.TEXT,
                            text=str(request.variables["text"]),
                        )
                    ],
                )
            ],
        )

    runtime = create_runtime()
    runtime.skill_register.register(
        SkillDefinition(
            name="summarize",
            description="Summarize text",
            capabilities=[SkillCapability.CHAT],
        ),
        summarize,
    )
    return create_interface(runtime)
