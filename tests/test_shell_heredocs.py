import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

from EvernightAI.core.error.tool import ToolPolicyError
from EvernightAI.infra.adapters.tool.shell_policy import inspected_commands
from tests.test_shell_command_policy import call_for, manager_for


SVG_TO_HTML = '''python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
p = Path('pelican-cycling.svg')
s = p.read_text()
s = s.replace('<path d="M-39 0H39"', '<path d="M-27.58-27.58L27.58 27.58"')
s = s.replace('M434 331Q418 370 436 401;M434 331Q471 356 495 404;M434 331Q482 410 493 463;M434 331Q417 410 433 461;M434 331Q418 370 436 401', 'M434 331Q418 370 436 404;M434 331Q471 356 492 404;M434 331Q482 410 492 460;M434 331Q417 410 436 460;M434 331Q418 370 436 404')
p.write_text(s)
ET.fromstring(s)
Path('pelican-cycling.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>鹈鹕骑车</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#e9efe9}svg{display:block;width:min(960px,100vw);height:auto;border-radius:20px;box-shadow:0 16px 60px #294c5620}</style>' + s + '</html>')
print('SVG XML validated; standalone HTML preview created.')
PY
'''


@pytest.mark.parametrize(
    "command",
    [
        SVG_TO_HTML,
        ["bash", "-lc", SVG_TO_HTML],
        'python - <<"PY"\nprint("ok")\nPY\n',
        "python - <<-'PY'\n\tprint('ok')\n\tPY\n",
        "python - 0<<'PY'\nprint('ok')\nPY\n",
        "python - <<'PY'\nprint('$(rm *) ; rm * ; &')\nPY\n",
        "python - <<'PY'\nprint('ok')\nPY\nunknown-program\n",
        "sh <<'SH'\necho ok\nSH\n",
    ],
)
def test_opaque_heredoc_scripts_require_approval_instead_of_hard_rejection(
    tmp_path, command
):
    manager = manager_for(tmp_path, relaxed=True)
    decision = manager.authorize(call_for(command))
    assert not decision.allowed
    assert decision.requires_approval
    assert decision.approval_request is not None
    assert decision.approval_request.tool_call["arguments"]["command"] == command
    assert manager.authorize(call_for(command, approved=True)).allowed


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX here-document syntax")
async def test_svg_edit_and_html_generation_run_only_after_approval(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    )
    source = tmp_path / "pelican-cycling.svg"
    original = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M-39 0H39" /></svg>'
    source.write_text(original)
    manager = manager_for(tmp_path, relaxed=True)
    with pytest.raises(ToolPolicyError):
        await manager.execute(call_for(SVG_TO_HTML))
    assert source.read_text() == original
    assert not (tmp_path / "pelican-cycling.html").exists()
    result = await manager.execute(call_for(SVG_TO_HTML, approved=True))
    assert result.tool_call_result["returncode"] == 0, result.tool_call_result["stderr"]
    ET.fromstring(source.read_text())
    assert 'd="M-27.58-27.58L27.58 27.58"' in source.read_text()
    assert "<title>鹈鹕骑车</title>" in (tmp_path / "pelican-cycling.html").read_text()


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'HTML'\n<div>$(rm *) ; rm * ; &</div>\nHTML\n",
        "cat <<'FIRST' <<'SECOND'\nignored $(rm *)\nFIRST\nliteral $(rm *)\nSECOND\n",
        "cat <<'TEXT'\n\"unterminated shell quote\nTEXT\necho done\n",
        "echo 'literal\n<<unquoted\ntext'\n",
    ],
)
def test_quoted_heredoc_data_is_not_inspected_as_executable_shell(tmp_path, command):
    assert manager_for(tmp_path, relaxed=True).authorize(call_for(command)).allowed


@pytest.mark.parametrize(
    "command",
    [
        "cat <<TEXT\n$(rm *)\nTEXT\n",
        "cat <<< 'text'",
        "cat <<'TEXT'\nmissing delimiter\n",
        "cat <<'TEXT'; echo done\ntext\nTEXT\n",
        "cat <<'TEXT' | sh\nrm *\nTEXT\n",
        "cat <<'TEXT' |\nsh\nrm *\nTEXT\n",
        "cat <<'TEXT' \\\n| sh\nrm *\nTEXT\n",
        "sh <<'SH'\nrm *\nSH\n",
        "sh <<'SH'\nrm note.txt\nSH\n",
        "sh <<'SH'\nCOMMAND=rm; $COMMAND note.txt\nSH\n",
        "python - <<'PY'\nprint('ok')\nPY\nrm *\n",
        "python - <<'PY'\nprint('ok')\nPY\nrm note.txt\n",
        "rm note.txt <<'DATA'\ntext\nDATA\n",
        ["bash", "-lc", "cat <<'TEXT'\ntext\nTEXT\nrm '$HOME/note.txt'\n"],
    ],
)
def test_heredocs_cannot_hide_deletion_or_unsupported_shell_syntax(tmp_path, command):
    decision = manager_for(tmp_path, relaxed=True).authorize(
        call_for(command, approved=True)
    )
    assert not decision.allowed
    assert not decision.requires_approval


def test_heredoc_commands_and_following_commands_still_follow_blacklists(tmp_path):
    manager = manager_for(tmp_path, relaxed=True, blocked={"python", "git push"})
    for command in [SVG_TO_HTML, "cat <<'TEXT'\ntext\nTEXT\ngit push\n"]:
        decision = manager.authorize(call_for(command, approved=True))
        assert not decision.allowed
        assert not decision.requires_approval
        assert "blocked" in (decision.reason or "")


def test_shell_heredoc_bodies_are_inspected_as_shell_commands(tmp_path):
    command = "sh <<'SH'\necho ok\nunknown-program\nSH\n"
    assert ["unknown-program"] in inspected_commands(command, ignore_redirections=True)
    manager = manager_for(tmp_path, relaxed=True, blocked={"unknown-program"})
    assert not manager.authorize(call_for(command, approved=True)).allowed


def test_unicode_digits_are_not_treated_as_shell_file_descriptors(tmp_path):
    decision = manager_for(tmp_path, relaxed=True).authorize(
        call_for("²<<'DATA'\nliteral text\nDATA\n")
    )
    assert not decision.allowed
    assert decision.requires_approval


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX here-document syntax")
async def test_heredoc_body_stays_literal_and_following_commands_execute(tmp_path):
    command = "cat <<'TEXT' > page.html\n<div>$(touch injected) ; &</div>\nTEXT\ncat page.html\n"
    result = await manager_for(tmp_path, relaxed=True).execute(call_for(command))
    assert result.tool_call_result["returncode"] == 0
    assert result.tool_call_result["stdout"] == "<div>$(touch injected) ; &</div>\n"
    assert not (tmp_path / "injected").exists()
