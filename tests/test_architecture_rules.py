import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "EvernightAI"
CORE_ROOT = PACKAGE_ROOT / "core"
APPLICATION_ROOT = PACKAGE_ROOT / "application"
INFRA_ROOT = PACKAGE_ROOT / "infra"
INTERFACE_ROOT = PACKAGE_ROOT / "interface"
BOOTSTRAP_ROOT = PACKAGE_ROOT / "bootstrap"
ENTRYPOINT_ROOT = PACKAGE_ROOT / "entrypoint"

ENTRYPOINT_ALLOWED_EVERNIGHTAI_IMPORTS = (
    "EvernightAI.bootstrap.",
    "EvernightAI.core.error.",
    "EvernightAI.core.protocol.interface",
    "EvernightAI.entrypoint.",
    "EvernightAI.interface.cli.",
)
ENTRYPOINT_FORBIDDEN_ASSEMBLY_CALLS = {
    "AgentApplication",
    "AgentRunApplication",
    "ChatApplication",
    "ContextManager",
    "EvernightInterface",
    "MemoryManager",
    "ProviderFactory",
    "ProviderManager",
    "RuntimeKernel",
    "SkillApplication",
    "SkillManager",
    "SkillRegister",
    "ToolManager",
    "create_http_app",
    "create_interface",
    "create_runtime",
    "create_sqlite_runtime",
}


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


def test_interface_and_entrypoint_do_not_reach_through_interface_runtime() -> None:
    violations: list[str] = []

    for root in [INTERFACE_ROOT, ENTRYPOINT_ROOT]:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "runtime"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "interface"
                ):
                    violations.append(f"{_rel(path)} reads interface.runtime")

    assert violations == []


def test_http_protocols_live_in_http_protocol_module() -> None:
    violations: list[str] = []
    protocol_path = INTERFACE_ROOT / "http" / "protocol.py"

    for path in _python_files(INTERFACE_ROOT / "http"):
        if path == protocol_path:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Protocol"):
                violations.append(f"{_rel(path)} defines {node.name}")

    assert violations == []


def test_inner_layers_do_not_depend_on_entrypoint_modules() -> None:
    violations: list[str] = []

    for root in [
        CORE_ROOT,
        APPLICATION_ROOT,
        INFRA_ROOT,
        INTERFACE_ROOT,
        BOOTSTRAP_ROOT,
    ]:
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


def test_entrypoint_does_not_depend_on_application_or_infra_modules() -> None:
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

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_application_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")
                if _is_infra_dependency(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_entrypoint_gets_assembled_runtime_interface_and_app_from_bootstrap() -> None:
    violations: list[str] = []

    for path in _python_files(ENTRYPOINT_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden_entrypoint_import(alias.name):
                        violations.append(f"{_rel(path)} imports {alias.name}")

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_forbidden_entrypoint_import(module):
                    imported = ", ".join(alias.name for alias in node.names)
                    violations.append(f"{_rel(path)} imports {imported} from {module}")

            if isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                if call_name in ENTRYPOINT_FORBIDDEN_ASSEMBLY_CALLS:
                    violations.append(f"{_rel(path)} calls {call_name}")

    assert violations == []


def test_inner_layers_do_not_depend_on_bootstrap_modules() -> None:
    violations: list[str] = []

    for root in [CORE_ROOT, APPLICATION_ROOT, INFRA_ROOT, INTERFACE_ROOT]:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_bootstrap_dependency(alias.name):
                            violations.append(f"{_rel(path)} imports {alias.name}")

                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if _is_bootstrap_dependency(module):
                        imported = ", ".join(alias.name for alias in node.names)
                        violations.append(f"{_rel(path)} imports {imported} from {module}")

    assert violations == []


def test_only_bootstrap_and_infra_depend_on_infra_modules() -> None:
    violations: list[str] = []

    for path in _python_files(PACKAGE_ROOT):
        if _is_under(path, BOOTSTRAP_ROOT) or _is_under(path, INFRA_ROOT):
            continue

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


def test_init_files_are_comment_only() -> None:
    violations: list[str] = []

    for path in _python_files(PACKAGE_ROOT):
        if path.name != "__init__.py":
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if tree.body:
            violations.append(f"{_rel(path)} contains executable statements")

    assert violations == []


def test_provider_chat_stream_uses_domain_stream_protocol() -> None:
    violations: list[str] = []

    for root in [CORE_ROOT, APPLICATION_ROOT, INFRA_ROOT]:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if node.name != "chat_stream":
                        continue
                    annotation = node.returns
                    if annotation is None:
                        violations.append(f"{_rel(path)} chat_stream lacks return type")
                        continue

                    annotation_name = _annotation_name(annotation)
                    if annotation_name != "ChatStreamProtocol":
                        violations.append(
                            f"{_rel(path)} chat_stream returns {annotation_name}"
                        )

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


def _is_bootstrap_dependency(module: str) -> bool:
    return module == "EvernightAI.bootstrap" or module.startswith(
        "EvernightAI.bootstrap."
    )


def _is_forbidden_entrypoint_import(module: str) -> bool:
    if not module.startswith("EvernightAI."):
        return False

    return not module.startswith(ENTRYPOINT_ALLOWED_EVERNIGHTAI_IMPORTS)


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr

    return None


def _annotation_name(annotation: ast.expr) -> str:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Constant):
        return str(annotation.value)

    return annotation.__class__.__name__


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))
