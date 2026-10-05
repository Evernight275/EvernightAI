import os
import shlex

import pytest

from EvernightAI.infra.adapters.tool.shell_literals import literal_script_reason
from EvernightAI.infra.adapters.tool.shell_policy import literal_command_reason
from tests.test_shell_command_policy import call_for, manager_for


@pytest.mark.parametrize(
    "script",
    [
        "rm './a$*.txt'",
        r"rm ./a\$\*.txt",
        r'rm "./a\$*.txt"',
        "rm './a?[]${HOME}.txt'",
        "rm ./note.txt",
        "rm /tmp/note.txt",
        "echo '*' | grep '*'",
        "cat './a$b.txt' > './out$*.txt'",
    ],
)
def test_posix_literal_paths_preserve_special_characters(script):
    assert literal_script_reason(script) is None
    assert literal_command_reason(script, dialect="posix") is None


def test_quoted_read_paths_do_not_trigger_extra_approval(tmp_path):
    assert manager_for(tmp_path).authorize(call_for("cat './a$*.txt'")).allowed
    assert manager_for(tmp_path).authorize(call_for(r"cat ./a\$\*.txt")).allowed


def test_array_targets_remain_literal_even_when_named_like_shell_commands(tmp_path):
    command = ["rm", "--", "sh", "-c", "*"]
    assert manager_for(tmp_path).authorize(call_for(command)).requires_approval
    assert manager_for(tmp_path).authorize(call_for(command, approved=True)).allowed


@pytest.mark.parametrize(
    "script",
    [
        "rm $HOME/note.txt",
        'rm "$HOME/note.txt"',
        "rm ${HOME}/note.txt",
        "rm ~/note.txt",
        "rm *.txt",
        "rm a?.txt",
        "rm a[12].txt",
        "rm './a$'*.txt",
        r'rm "./a\\$*.txt"',
        "rm `pwd`/note.txt",
        "rm $(pwd)/note.txt",
        "rm ./a{1,2}.txt",
        "rm ./a{1..2}.txt",
        "cat <(pwd)",
        "rm 'unterminated",
        "echo $(rm './literal.txt')",
        "env PATH=/untrusted ls",
        "export X=one; ls",
        "X=one ls",
        "sudo X=one ls",
        'rm ""',
        "rm -rf",
        "find . -delete",
        "echo note.txt | xargs rm",
        ["sh", "-c", "rm $HOME/note.txt"],
        ["bash", "-lc", "rm *.txt"],
    ],
)
def test_expanded_or_indirect_paths_cannot_be_approved(tmp_path, script):
    decision = manager_for(tmp_path).authorize(call_for(script, approved=True))
    assert not decision.allowed
    assert not decision.requires_approval


@pytest.mark.parametrize(
    "script",
    [
        'del "%TEMP%\\note.txt"',
        'del "!TEMP!\\note.txt"',
        "del ^%TEMP%\\note.txt",
        'del "C:\\temp\\*.txt"',
    ],
)
def test_windows_expansion_is_not_disabled_by_quoting(script):
    assert literal_command_reason(script, dialect="cmd") is not None


def test_windows_literals_and_powershell_quoting():
    assert literal_script_reason('del "C:\\temp\\a$.txt"', "cmd") is None
    assert (
        literal_script_reason("Remove-Item -LiteralPath './a$*.txt'", "powershell")
        is None
    )
    assert (
        literal_script_reason('Remove-Item -LiteralPath "./a`$*.txt"', "powershell")
        is None
    )
    assert (
        literal_script_reason('Remove-Item "$env:TEMP/note.txt"', "powershell")
        is not None
    )
    assert (
        literal_command_reason(
            ["pwsh", "-Command", "Remove-Item -LiteralPath './a$*.txt'"],
            dialect="posix",
        )
        is None
    )
    assert (
        literal_command_reason(
            ["pwsh", "-Command", "Remove-Item './a$*.txt'"], dialect="posix"
        )
        is not None
    )


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX filenames and quoting")
@pytest.mark.parametrize(
    "style", ["single_quote", "backslash", "double_quote", "array", "absolute"]
)
async def test_special_filename_deletion_only_affects_the_literal_target(
    tmp_path, style
):
    target = tmp_path / "a$*.txt"
    target.write_text("target")
    other = tmp_path / "a$other.txt"
    other.write_text("keep")
    command = {
        "single_quote": "rm './a$*.txt'",
        "backslash": r"rm ./a\$\*.txt",
        "double_quote": r'rm "./a\$*.txt"',
        "array": ["rm", "./a$*.txt"],
        "absolute": "rm " + shlex.quote(str(target)),
    }[style]
    manager = manager_for(tmp_path)
    decision = manager.authorize(call_for(command))
    assert decision.requires_approval
    assert target.exists()
    result = await manager.execute(call_for(command, approved=True))
    assert result.tool_call_result["returncode"] == 0
    assert not target.exists()
    assert other.read_text() == "keep"


@pytest.mark.asyncio
async def test_even_preconfigured_environment_overrides_are_forbidden(tmp_path):
    call = call_for(["echo", "ok"], approved=True)
    call.tool_call["arguments"]["env"] = {"EVERNIGHT_TEST_VALUE": "ok"}
    decision = manager_for(tmp_path, env_keys={"EVERNIGHT_TEST_VALUE"}).authorize(call)
    assert not decision.allowed
    assert not decision.requires_approval
