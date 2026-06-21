import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "EvernightAI"
CORE_ROOT = PACKAGE_ROOT / "core"
APPLICATION_ROOT = PACKAGE_ROOT / "application"
INFRA_ROOT = PACKAGE_ROOT / "infra"
INTERFACE_ROOT = PACKAGE_ROOT / "interface"
ENTRYPOINT_ROOT = PACKAGE_ROOT / "entrypoint"


def test_core_only_depends_on_core_modules() -> None:
    violations: list[str] = []

    for path in _python_files(CORE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden_core_dependency(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")

            if isinstance(node, ast.ImportFrom):
                if node.level > 1:
                    violations.append(f"{_rel(path)} uses parent relative import")
                    continue

                module = node.module or ""
                imported_names = [alias.name for alias in node.names]
                if _is_forbidden_core_from_import(module, imported_names):
                    imported = ", ".join(imported_names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_application_does_not_depend_on_infra_modules() -> None:
    violations: list[str] = []

    for path in _python_files(APPLICATION_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_infra_dependency(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_infra_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_core_application_and_infra_do_not_depend_on_interface_modules() -> None:
    violations: list[str] = []

    for root in [CORE_ROOT, APPLICATION_ROOT, INFRA_ROOT]:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_interface_dependency(alias.name):
                            violations.append(f"{_rel(path)} imports {alias.name}")

                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if _is_interface_dependency(module):
                        imported = ", ".join(alias.name for alias in node.names)
                        violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_interface_does_not_depend_on_application_or_infra_modules() -> None:
    violations: list[str] = []

    for path in _python_files(INTERFACE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_application_dependency(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")
                    if _is_infra_dependency(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_application_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")
                if _is_infra_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_inner_layers_do_not_depend_on_entrypoint_modules() -> None:
    violations: list[str] = []

    for root in [CORE_ROOT, APPLICATION_ROOT, INFRA_ROOT, INTERFACE_ROOT]:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_entrypoint_dependency(alias.name):
                            violations.append(f"{_rel(path)} imports {alias.name}")

                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if _is_entrypoint_dependency(module):
                        imported = ", ".join(alias.name for alias in node.names)
                        violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_entrypoint_does_not_depend_on_application_infra_or_interface_modules() -> None:
    violations: list[str] = []

    for path in _python_files(ENTRYPOINT_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_application_dependency(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")
                    if _is_infra_dependency(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")
                    if _is_interface_dependency(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_application_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")
                if _is_infra_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")
                if _is_interface_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_init_files_are_comment_only() -> None:
    violations: list[str] = []

    for path in _python_files(PACKAGE_ROOT):
        if path.name != "__init__.py":
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if tree.body:
            violations.append(f"{_rel(path)} contains executable statements")

    assert violations == []


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _is_forbidden_core_dependency(module: str) -> bool:
    if module == "EvernightAI":
        return True
    if module.startswith("EvernightAI.") and not module.startswith("EvernightAI.core."):
        return True

    return False


def _is_forbidden_core_from_import(module: str, imported_names: list[str]) -> bool:
    if module == "EvernightAI":
        return True
    if module.startswith("EvernightAI.") and not module.startswith("EvernightAI.core."):
        return True

    return False


def _is_infra_dependency(module: str) -> bool:
    return module == "EvernightAI.infra" or module.startswith("EvernightAI.infra.")


def _is_application_dependency(module: str) -> bool:
    return module == "EvernightAI.application" or module.startswith(
        "EvernightAI.application."
    )


def _is_interface_dependency(module: str) -> bool:
    return module == "EvernightAI.interface" or module.startswith(
        "EvernightAI.interface."
    )


def _is_entrypoint_dependency(module: str) -> bool:
    return module == "EvernightAI.entrypoint" or module.startswith(
        "EvernightAI.entrypoint."
    )


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))
