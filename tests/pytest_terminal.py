"""Project-local presentation; pytest still owns reports, statistics and exits."""

import platform
import time
from collections.abc import Generator
from typing import Any

import pytest
from _pytest._io.wcwidth import wcswidth
from _pytest.terminal import TerminalReporter


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("EvernightAI terminal")
    group.addoption(
        "--terminal-style",
        choices=("dashboard", "plain"),
        default="dashboard",
        help="Terminal presentation (default: dashboard; plain uses native pytest)",
    )


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("terminal_style") == "plain" or hasattr(config, "workerinput"):
        return
    reporter = config.pluginmanager.getplugin("terminalreporter")
    if not isinstance(reporter, TerminalReporter) or config.getoption("collectonly"):
        return
    if config.option.tbstyle == "auto":
        config.option.tbstyle = "short"
    config.pluginmanager.unregister(reporter)
    config.pluginmanager.register(DashboardReporter(reporter), "terminalreporter")


class DashboardReporter:
    """Delegate native reporting hooks, replacing only per-test presentation.

    The adapter uses pytest's terminal reporter internals in this module only;
    retaining that reporter preserves assertion diffs and other plugins' summaries.
    """

    def __init__(self, reporter: TerminalReporter) -> None:
        self._reporter = reporter
        self._total = 0
        self._completed = 0
        self._last_bucket = -1
        self._last_draw = 0.0
        self._current = ""
        self._durations: dict[tuple[str, str], float] = {}
        self._slowest: list[tuple[float, str]] = []
        config = reporter.config
        self._live = bool(reporter.isatty) and config.getoption("capture") != "no"
        self._live = self._live and not config.getini("log_cli")
        self._live = (
            self._live and config.get_verbosity(pytest.Config.VERBOSITY_TEST_CASES) <= 0
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._reporter, name)

    def __dir__(self) -> list[str]:
        # Pluggy discovers hooks through dir(), including the delegated hooks.
        return sorted(set(dir(self._reporter)) | set(dir(type(self))))

    def pytest_report_header(self, config: pytest.Config) -> list[str]:
        return [
            "EvernightAI test dashboard",
            *self._reporter.pytest_report_header(config),
        ]

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self._reporter.pytest_collection_finish(session)
        self._start_display(len(session.items))

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: Any, ids: list[str]) -> None:
        if not self._total:
            self._start_display(len(ids))

    def _start_display(self, total: int) -> None:
        self._total = total
        if self._total:
            self._reporter.write_sep(
                "-",
                f"EvernightAI | Python {platform.python_version()} | {self._total} tests",
                cyan=True,
                bold=True,
            )
            self._draw(force=True)

    def pytest_runtest_logstart(
        self, nodeid: str, location: tuple[str, int | None, str]
    ) -> None:
        self._current = nodeid
        if self._live:
            self._draw(force=True)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        reporter = self._reporter
        category, _, _ = reporter.config.hook.pytest_report_teststatus(
            report=report, config=reporter.config
        )
        reporter._tests_ran = True
        reporter._add_stats(category, [report])
        if getattr(report, "context", None) is not None:
            return  # Subtests have their own statistics, but aren't collected items.
        key = (getattr(report, "worker_id", ""), report.nodeid)
        self._durations[key] = self._durations.get(key, 0.0) + report.duration
        if report.when != "teardown":
            return
        self._completed += 1
        self._current = report.nodeid
        self._slowest.append((self._durations.pop(key), report.nodeid))
        verbose = reporter.config.get_verbosity(pytest.Config.VERBOSITY_TEST_CASES) > 0
        self._draw(force=verbose and not self._live)

    @pytest.hookimpl(wrapper=True)
    def pytest_sessionfinish(
        self, session: pytest.Session, exitstatus: int
    ) -> Generator[None, None, None]:
        if self._live and self._total:
            self._draw(force=True)
            self._reporter.write("\n")
        return (yield from self._reporter.pytest_sessionfinish(session, exitstatus))

    def _draw(self, *, force: bool = False) -> None:
        if not self._total:
            return
        now = time.monotonic()
        bucket = min(10, self._completed * 10 // self._total)
        if not force:
            if self._live and now - self._last_draw < 0.05:
                return
            if not self._live and bucket == self._last_bucket:
                return
        self._last_draw = now
        self._last_bucket = bucket
        reporter = self._reporter
        counts = " ".join(
            f"{label} {len(reporter.stats.get(category, []))}"
            for category, label in (
                ("passed", "PASS"),
                ("failed", "FAIL"),
                ("error", "ERROR"),
                ("skipped", "SKIP"),
                ("xfailed", "XFAIL"),
                ("xpassed", "XPASS"),
            )
            if category in {"passed", "failed"} or reporter.stats.get(category)
        )
        fraction = min(1.0, self._completed / self._total)
        width = max(4, min(20, reporter._tw.fullwidth // 6))
        filled = int(width * fraction)
        bar = "#" * filled + "-" * (width - filled)
        line = f"[{bar}] {fraction:4.0%} {self._completed}/{self._total} | {counts}"
        if self._current:
            current = self._current.rsplit("::", 1)[-1] if self._live else self._current
            line += f" | {current}"
        if self._live:
            line = _fit(line, max(10, reporter._tw.fullwidth - 1))
            reporter.rewrite(line, erase=True, cyan=True)
            reporter.flush()
        else:
            reporter.write_line(line)
            reporter.flush()


def _fit(text: str, width: int) -> str:
    if wcswidth(text) <= width:
        return text
    while text and wcswidth(text + "...") > width:
        text = text[:-1]
    return text + "..."


def pytest_terminal_summary(terminalreporter: TerminalReporter) -> None:
    reporter = terminalreporter.config.pluginmanager.getplugin("terminalreporter")
    if not isinstance(reporter, DashboardReporter):
        return
    if reporter.config.option.durations is not None or not reporter._slowest:
        return
    reporter.write_sep("-", "Slowest tests (setup + call + teardown)", cyan=True)
    for duration, nodeid in sorted(reporter._slowest, reverse=True)[:5]:
        reporter.write_line(f"  {duration:8.3f}s  {nodeid}")
