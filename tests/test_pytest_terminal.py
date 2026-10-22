import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_pytest(
    tmp_path: Path, source: str, *args: str
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "test_sample.py").write_text(source, encoding="utf-8")
    env = os.environ.copy()
    root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join([root, env.get("PYTHONPATH", "")])
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.pytest_terminal",
            "--color=no",
            "-ra",
            *args,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_dashboard_preserves_failures_skips_and_exit_code(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        """import pytest

def test_pass():
    assert True

def test_diff():
    assert {'answer': 1} == {'answer': 2}

@pytest.mark.skip(reason='provider unavailable')
def test_skip():
    pass

@pytest.mark.xfail(reason='known issue')
def test_xfail():
    assert False
""",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "EvernightAI | Python" in result.stdout
    assert "4 tests" in result.stdout
    assert "100% 4/4 | PASS 1 FAIL 1 SKIP 1 XFAIL 1" in result.stdout
    assert "test_sample.py::test_diff" in result.stdout
    assert "AssertionError" in result.stdout
    assert "{'answer': 1}" in result.stdout
    assert "provider unavailable" in result.stdout
    assert "1 failed, 1 passed, 1 skipped, 1 xfailed" in result.stdout
    assert "Slowest tests (setup + call + teardown)" in result.stdout
    assert "\x1b[" not in result.stdout
    assert "INTERNALERROR" not in result.stdout


@pytest.mark.parametrize("phase", ["setup", "teardown"])
def test_dashboard_preserves_fixture_errors(tmp_path: Path, phase: str) -> None:
    body = (
        "    raise RuntimeError('fixture broke')\n    yield"
        if phase == "setup"
        else "    yield\n    raise RuntimeError('fixture broke')"
    )
    result = run_pytest(
        tmp_path,
        f"import pytest\n@pytest.fixture\ndef resource():\n{body}\n"
        "def test_resource(resource):\n    pass\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "100% 1/1" in result.stdout
    assert "ERROR 1" in result.stdout
    assert "RuntimeError: fixture broke" in result.stdout
    assert "1 error" in result.stdout


@pytest.mark.parametrize("args", [("--terminal-style=plain",), ("--collect-only",)])
def test_native_output_can_be_used(tmp_path: Path, args: tuple[str, ...]) -> None:
    result = run_pytest(tmp_path, "def test_ok():\n    pass\n", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EvernightAI test dashboard" not in result.stdout
    assert "Slowest tests" not in result.stdout


def test_dashboard_with_xdist(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        "import pytest\n@pytest.mark.parametrize('i', range(4))\n"
        "def test_parallel(i):\n    assert i >= 0\n",
        "-n",
        "2",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout
    assert "100% 4/4 | PASS 4 FAIL 0" in result.stdout


def test_explicit_traceback_and_duration_options_are_preserved(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        "def test_diff():\n    assert 1 == 2\n",
        "--tb=no",
        "--durations=1",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "AssertionError" not in result.stdout
    assert "slowest 1 durations" in result.stdout
    assert "Slowest tests (setup + call + teardown)" not in result.stdout


def test_early_stop_does_not_claim_all_tests_completed(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        "def test_fail():\n    assert False\ndef test_later():\n    pass\n",
        "-x",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "50% 1/2 | PASS 0 FAIL 1" in result.stdout
    assert "100%" not in result.stdout


@pytest.mark.parametrize(
    ("source", "code", "message"),
    [
        ("", 5, "no tests ran"),
        ("def test_broken(\n", 2, "SyntaxError"),
    ],
)
def test_empty_and_invalid_suites_keep_native_diagnostics(
    tmp_path: Path, source: str, code: int, message: str
) -> None:
    result = run_pytest(tmp_path, source)
    assert result.returncode == code, result.stdout + result.stderr
    assert message in result.stdout
    assert "INTERNALERROR" not in result.stdout


def test_xpass_outcomes_remain_distinct(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.xfail(reason='fixed')\n"
        "def test_xpass():\n    pass\n"
        "@pytest.mark.xfail(reason='strict fixed', strict=True)\n"
        "def test_strict_xpass():\n    pass\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "100% 2/2 | PASS 0 FAIL 1 XPASS 1" in result.stdout
    assert "[XPASS(strict)] strict fixed" in result.stdout


def test_subtests_do_not_inflate_collected_progress(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        "def test_subcases(subtests):\n"
        "    for i in range(2):\n"
        "        with subtests.test(i=i):\n"
        "            assert i == 0\n",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "100% 1/1 | PASS 0 FAIL 2" in result.stdout
    assert "2/1" not in result.stdout
    assert "contains 1 failed subtest" in result.stdout


def test_uncaptured_output_and_verbose_results_remain_readable(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        "def test_print():\n    print('application output')\n",
        "-s",
        "-v",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "application output\n" in result.stdout
    assert "test_sample.py::test_print" in result.stdout
    assert "\r" not in result.stdout


def test_dashboard_keeps_coverage_and_junit_reports(tmp_path: Path) -> None:
    result = run_pytest(
        tmp_path,
        "def test_ok():\n    assert True\n",
        "--cov=test_sample",
        "--cov-report=term",
        "--junitxml=results.xml",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "100% 1/1 | PASS 1 FAIL 0" in result.stdout
    assert "TOTAL" in result.stdout
    assert 'failures="0"' in (tmp_path / "results.xml").read_text(encoding="utf-8")
