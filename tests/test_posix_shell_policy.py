import pytest
from pydantic import ValidationError

from EvernightAI.infra.adapters.tool.restricted_shell import RestrictedShellTool
from EvernightAI.infra.adapters.tool.shell_policy import ShellCommandPolicy
from EvernightAI.infra.adapters.tool.shell_syntax import parse_script
from EvernightAI.interface.cli.schema import EvernightConfig, ShellToolConfig


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "EvernightAI.infra.adapters.tool.shell_policy.shutil.which",
        lambda name, **kwargs: str(tmp_path.parent / "system-bin" / name),
    )

    def create(level="read_only", **kwargs):
        return ShellCommandPolicy(root=tmp_path, level=level, dialect="posix", **kwargs)

    return create


@pytest.mark.parametrize("level", ["read_only", "workspace_write", "trusted_dev"])
@pytest.mark.parametrize(
    "command",
    [
        "sort --compress-program=sh input",
        "sort --unknown input",
        "pwd extra",
        "uniq a b c",
        "rg --pre=sh x",
        "git push origin main",
        "uv publish",
        "sudo ls",
        "./ls",
        "bin/cat",
        "python -c 'print(1)'",
        "f() { echo hi; }; f",
        "for x in a; do echo x; done",
        "echo $(pwd)",
        "cat <(pwd)",
        "echo $((1+1))",
        "cat <<EOF\n$HOME\nEOF",
        "echo '",
        "cat code | sh",
        "sh < code",
        "cat code | python -",
        "cat code | node",
        "sh <<'EOF'\necho hi\nEOF",
    ],
)
def test_unknown_execution_and_publishing_always_ask(policy, level, command):
    assert policy(level).evaluate(command).kind == "ask"


@pytest.mark.parametrize(
    "command", ["uniq IN OUT", "echo hello > out", "touch out", "mkdir dir", "tee out"]
)
@pytest.mark.parametrize(
    "level,expected",
    [("read_only", "ask"), ("workspace_write", "allow"), ("trusted_dev", "allow")],
)
def test_literal_workspace_write_levels(policy, command, level, expected):
    assert policy(level).evaluate(command).kind == expected


@pytest.mark.parametrize(
    "command",
    [
        "curl https://example.com",
        "git status",
        "pytest -q",
        "npm test",
        "uv sync",
        "uv run pytest -q",
        "python -m pytest -q",
    ],
)
@pytest.mark.parametrize(
    "level,expected",
    [("read_only", "ask"), ("workspace_write", "ask"), ("trusted_dev", "allow")],
)
def test_network_and_project_code_require_trusted_dev(policy, command, level, expected):
    assert policy(level).evaluate(command).kind == expected


@pytest.mark.parametrize(
    "key",
    [
        "PATH",
        "LD_PRELOAD",
        "DYLD_LIBRARY_PATH",
        "BASH_ENV",
        "ENV",
        "IFS",
        "PYTHONPATH",
        "PYTHONHOME",
        "NODE_OPTIONS",
        "APP_CONFIG_PATH",
        "GIT_CONFIG_COUNT",
    ],
)
def test_all_environment_channels_ask_even_in_trusted_dev(policy, key):
    checker = policy("trusted_dev")
    for command in [
        f"{key}=x cat file",
        f"env {key}=x cat file",
        f"export {key}=x",
        f"set {key}=x",
    ]:
        assert checker.evaluate(command).kind == "ask"
    assert checker.evaluate(["cat", "file"], {key: "x"}).kind == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "OTHER=x cat file",
        "env OTHER=x cat file",
        "export OTHER=x",
        "sh -c 'export OTHER=x'",
    ],
)
def test_environment_allowlist_is_hard_and_recursive(policy, command):
    assert policy(allowed_env_keys={"SAFE"}).evaluate(command).kind == "reject"


def test_write_targets_resolve_symlinks_and_cwd(policy, tmp_path):
    (tmp_path / "dir").mkdir()
    (tmp_path / "escape").symlink_to(tmp_path.parent, target_is_directory=True)
    checker = policy("workspace_write")
    assert checker.evaluate("echo hi > escape/out").kind == "ask"
    assert checker.evaluate("uniq in ../out").kind == "ask"
    assert checker.evaluate("cd dir && sh -c 'touch ../../out'").kind == "ask"
    assert checker.evaluate("echo hi > $OUT").kind == "ask"


def test_plain_allowlist_does_not_trust_arguments(policy):
    checker = policy(trusted_commands={"uv", "sort"})
    assert checker.evaluate("uv arbitrary-command").kind == "ask"
    assert checker.evaluate("sort --compress-program=sh").kind == "ask"
    assert (
        policy(trusted_commands={"uv *"}).evaluate("uv arbitrary-command").kind
        == "allow"
    )
    assert policy(trusted_commands={"uv *"}).evaluate("uv publish").kind == "ask"


def test_input_capability_comes_from_spec(policy):
    assert not policy().evaluate("cat").stdin_is_code
    assert policy("trusted_dev").evaluate("uv run pytest").stdin_is_code
    assert policy().evaluate("sh -c 'cat'").stdin_is_code
    assert policy().evaluate("cat < data").kind == "allow"


def test_pipeline_and_subshell_structure_is_retained():
    tree = parse_script("(cat data | sh)")
    assert tree.children[0].kind == "subshell"
    commands = tree.commands()
    assert commands[1].argv[0].literal == "sh"
    assert commands[1].stdin


def test_legacy_config_has_migration_message():
    with pytest.raises(ValidationError, match="migrate to approval_level"):
        ShellToolConfig.model_validate({"relaxed_approval": False})


def test_trusted_dev_requires_bubblewrap_in_config_and_direct_tool(tmp_path):
    with pytest.raises(ValidationError, match="requires the bubblewrap"):
        EvernightConfig.model_validate(
            {"tools": {"shell": {"approval_level": "trusted_dev"}}}
        )
    with pytest.raises(ValueError, match="requires the bubblewrap"):
        RestrictedShellTool(
            allowed_commands=set(),
            working_directory=tmp_path,
            approval_level="trusted_dev",
        )


def test_nested_depth_limit(policy):
    assert policy().evaluate("pwd", depth=17).kind == "ask"


def test_find_checks_actions_after_exec(policy):
    assert (
        policy("trusted_dev").evaluate(r"find . -exec grep X {} \; -fprint output").kind
        == "ask"
    )


def test_allowed_environment_assignments_do_not_treat_argv_as_keys(policy):
    assert (
        policy(allowed_env_keys={"SAFE"}).evaluate("env SAFE=x cat file").kind
        == "allow"
    )


@pytest.mark.parametrize(
    "command",
    [
        "if true; then rm *; fi",
        "f() { rm *; }; f",
        ["bash", "-lc", "if true; then rm *; fi"],
        ["/bin/sh", "-c", "if true; then rm *; fi"],
    ],
)
def test_opaque_constructs_cannot_hide_nonliteral_deletion(policy, command):
    assert policy().evaluate(command).kind == "reject"


def test_opaque_control_flow_cannot_hide_blocked_commands(policy):
    assert (
        policy(blocked_commands={"forbidden"})
        .evaluate("if true; then forbidden; fi")
        .kind
        == "reject"
    )


def test_automatic_project_virtualenv_does_not_establish_trust(policy, tmp_path):
    directory = tmp_path / ".venv" / "bin"
    directory.mkdir(parents=True)
    executable = directory / "cat"
    executable.write_text("#!/bin/sh\nexec sh\n")
    executable.chmod(0o755)
    assert policy("trusted_dev").evaluate("cat").kind == "ask"


def test_opaque_commands_still_expose_environment_for_hard_limits(policy):
    assert (
        policy(allowed_env_keys={"SAFE"})
        .evaluate("if true; then export OTHER=x; fi")
        .kind
        == "reject"
    )


def test_wildcard_trust_cannot_override_known_system_effects(policy):
    assert (
        policy("trusted_dev", trusted_commands={"kill *"}).evaluate("kill -9 123").kind
        == "ask"
    )


def test_shell_heredocs_recursively_enforce_hard_rules(policy):
    script = "sh <<'SH'\nif true; then forbidden; fi\nSH\n"
    assert policy(blocked_commands={"forbidden"}).evaluate(script).kind == "reject"
    script = "sh <<'SH'\nexport OTHER=x\nSH\n"
    assert policy(allowed_env_keys={"SAFE"}).evaluate(script).kind == "reject"


def test_find_propagates_child_stdin_and_environment_capabilities(policy):
    checker = policy(trusted_commands={"custom *"})
    assert checker.evaluate(r"find . -exec custom {} \;").stdin_is_code
    assert (
        policy(allowed_env_keys={"SAFE"})
        .evaluate(r"find . -exec env OTHER=x cat {} \;")
        .kind
        == "reject"
    )
