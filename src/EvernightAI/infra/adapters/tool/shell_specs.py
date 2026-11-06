"""Declared argument grammars; absence of a declaration means UNKNOWN."""

from dataclasses import dataclass
from enum import StrEnum


class Effect(StrEnum):
    READ = "READ"
    WORKSPACE_WRITE = "WORKSPACE_WRITE"
    NETWORK = "NETWORK"
    PROJECT_CODE = "PROJECT_CODE"
    PUBLISH = "PUBLISH"
    DELETE = "DELETE"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Spec:
    flags: frozenset[str] = frozenset()
    valued: frozenset[str] = frozenset()
    max_args: int | None = None
    effect: Effect = Effect.READ
    write_positions: tuple[int, ...] = ()
    stdin_is_code: bool = False


def spec(
    flags: str = "",
    valued: str = "",
    max_args: int | None = None,
    effect: Effect = Effect.READ,
    writes: tuple[int, ...] = (),
) -> Spec:
    return Spec(
        frozenset(flags.split()), frozenset(valued.split()), max_args, effect, writes
    )


SPECS: dict[str, Spec] = {
    "pwd": spec("-L -P", max_args=0),
    "whoami": spec("--help --version", max_args=0),
    "true": spec(max_args=0),
    "false": spec(max_args=0),
    "cd": spec("-L -P", max_args=1),
    "echo": spec("-n -e -E"),
    "printf": spec(),
    "ls": spec(
        "-a -A -l -h -d -R -r -t -S -1 -F -p -i -s -n --all --almost-all --human-readable --directory --recursive --color",
        "--sort --time --color",
    ),
    "cat": spec("-n -b -s -v -e -t -A -E -T --number --show-all"),
    "head": spec("-q -v", "-n -c --lines --bytes"),
    "tail": spec("-q -v -f -F", "-n -c --lines --bytes --pid"),
    "wc": spec("-c -m -l -w -L --bytes --chars --lines --words --max-line-length"),
    "cut": spec(
        "-s --complement --only-delimited",
        "-b -c -f -d --bytes --characters --fields --delimiter --output-delimiter",
    ),
    "grep": spec(
        "-i -v -n -r -R -l -L -c -w -x -F -E -G -P -o -h -H -s -q -a -I --ignore-case --invert-match --line-number --files-with-matches --count --fixed-strings",
        "-e -f -m -A -B -C --regexp --file --max-count --include --exclude --exclude-dir",
    ),
    "rg": spec(
        "-i -n -l -L -c -w -x -F -o -v -s -S -a -u --files --hidden --no-ignore --count --fixed-strings --line-number --no-heading --heading --stats",
        "-e -f -g -t -T -m -A -B -C --glob --type --type-not --max-count --max-depth --encoding --color",
    ),
    "sort": spec(
        "-r -n -g -h -V -M -f -b -d -i -s -u -c -C -z --reverse --numeric-sort --unique --stable --check",
        "-k -t -S --key --field-separator --buffer-size",
    ),
    "uniq": spec(
        "-c -d -D -u -i -z --count --repeated --unique",
        "-f -s -w --skip-fields --skip-chars --check-chars",
        2,
        writes=(1,),
    ),
    "which": spec("-a", max_args=None),
    "touch": spec(
        "-c -a -m --no-create",
        "-t -d -r --date --reference",
        effect=Effect.WORKSPACE_WRITE,
        writes=(-2,),
    ),
    "mkdir": spec(
        "-p -v --parents --verbose",
        "-m --mode",
        effect=Effect.WORKSPACE_WRITE,
        writes=(-2,),
    ),
    "tee": spec(
        "-a -i --append --ignore-interrupts",
        effect=Effect.WORKSPACE_WRITE,
        writes=(-2,),
    ),
    "cp": spec(
        "-p -f -n -v --preserve",
        effect=Effect.WORKSPACE_WRITE,
        writes=(-1,),
    ),
    "mv": spec("-f -n -v", effect=Effect.WORKSPACE_WRITE, writes=(-2,)),
    "git status": spec(
        "--short --branch --porcelain -s -b --untracked-files",
        "--untracked-files",
        0,
        effect=Effect.PROJECT_CODE,
    ),
    # External diff drivers, textconv, pagers and hooks require a stronger effect.
    "git diff": spec(
        "--stat --name-only --name-status --cached --staged --no-ext-diff --no-textconv",
        effect=Effect.PROJECT_CODE,
    ),
    "git log": spec(
        "--oneline --stat --all --decorate",
        "-n --max-count",
        effect=Effect.PROJECT_CODE,
    ),
    "git ls-files": spec("--cached --others --exclude-standard -z"),
    "git rev-parse": spec(
        "--show-toplevel --is-inside-work-tree --show-prefix --verify"
    ),
    "git fetch": spec("--all --prune --tags", effect=Effect.NETWORK),
    "git push": spec(effect=Effect.PUBLISH),
    "uv --version": spec(max_args=0),
    "uv version": spec(max_args=0),
    "uv sync": spec(
        "--frozen --locked --no-dev --all-extras", effect=Effect.PROJECT_CODE
    ),
    "uv publish": spec(effect=Effect.PUBLISH),
    "npm publish": spec(effect=Effect.PUBLISH),
    "npm test": spec(effect=Effect.PROJECT_CODE),
    "npm run": spec(max_args=1, effect=Effect.PROJECT_CODE),
    "pnpm run": spec(max_args=1, effect=Effect.PROJECT_CODE),
    "pytest": spec(
        "-q -v -s -x --collect-only --disable-warnings",
        "-k -m --maxfail",
        effect=Effect.PROJECT_CODE,
    ),
    "curl": spec(
        "-I -s -S -L -f --head --silent --show-error --location --fail",
        "--max-time --connect-timeout",
        effect=Effect.NETWORK,
    ),
}

STDIN_CODE = frozenset(
    {
        "sh",
        "bash",
        "dash",
        "zsh",
        "fish",
        "python",
        "python3",
        "node",
        "perl",
        "ruby",
        "xargs",
        "env",
        "uv",
    }
)


def arguments(specification: Spec, args: list[str]) -> list[str] | None:
    positions: list[str] = []
    index = 0
    options = True
    while index < len(args):
        arg = args[index]
        if arg == "--" and options:
            options = False
        elif options and arg.startswith("-") and arg != "-":
            flag, equals, _ = arg.partition("=")
            if flag in specification.valued:
                if not equals:
                    index += 1
                    if index >= len(args):
                        return None
            elif not equals and flag in specification.flags:
                pass
            elif not arg.startswith("--"):
                # Short options may be combined; a valued option consumes the suffix.
                for offset, letter in enumerate(arg[1:], 1):
                    short = "-" + letter
                    if short in specification.valued:
                        if offset == len(arg) - 1:
                            index += 1
                            if index >= len(args):
                                return None
                        break
                    if short not in specification.flags:
                        return None
            else:
                return None
        else:
            positions.append(arg)
        index += 1
    if specification.max_args is not None and len(positions) > specification.max_args:
        return None
    return positions


STDIN_SPECS = {
    name: Spec(effect=Effect.UNKNOWN, stdin_is_code=True) for name in STDIN_CODE
}


SYSTEM_COMMANDS = frozenset(
    {
        "sudo",
        "su",
        "doas",
        "kill",
        "pkill",
        "killall",
        "systemctl",
        "service",
        "chmod",
        "chown",
        "chgrp",
        "apt",
        "apt-get",
        "dnf",
        "yum",
        "pacman",
        "mount",
        "umount",
        "reboot",
        "shutdown",
    }
)
