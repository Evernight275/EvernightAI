from pathlib import Path

from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.restricted_filesystem import (
    RestrictedAppendTextFileTool,
    RestrictedApplyTextPatchTool,
    RestrictedCopyPathTool,
    RestrictedDeletePathTool,
    RestrictedFileHashTool,
    RestrictedFindPathsTool,
    RestrictedListDirectoryTool,
    RestrictedMakeDirectoryTool,
    RestrictedMovePathTool,
    RestrictedPathInfoTool,
    RestrictedReadTextFileTool,
    RestrictedReadJsonFileTool,
    RestrictedReadTextFileLinesTool,
    RestrictedSearchTextFilesTool,
    RestrictedWriteJsonFileTool,
    RestrictedWriteTextFileTool,
)


def register_restricted_filesystem_tools(
    register: ToolRegisterProtocol,
    *,
    root_directory: str | Path,
    max_read_chars: int = 12000,
    max_directory_entries: int = 100,
    max_search_results: int = 100,
    allow_overwrite: bool = False,
    project_directories: dict[str, str | Path] | None = None,
) -> None:
    read_tool = RestrictedReadTextFileTool(
        root_directory=root_directory,
        project_directories=project_directories,
        max_chars=max_read_chars,
    )
    write_tool = RestrictedWriteTextFileTool(
        root_directory=root_directory,
        project_directories=project_directories,
        allow_overwrite=allow_overwrite,
    )
    append_tool = RestrictedAppendTextFileTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    list_tool = RestrictedListDirectoryTool(
        root_directory=root_directory,
        project_directories=project_directories,
        max_entries=max_directory_entries,
    )
    find_tool = RestrictedFindPathsTool(
        root_directory=root_directory,
        project_directories=project_directories,
        max_results=max_search_results,
    )
    search_tool = RestrictedSearchTextFilesTool(
        root_directory=root_directory,
        project_directories=project_directories,
        max_results=max_search_results,
    )
    read_lines_tool = RestrictedReadTextFileLinesTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    move_tool = RestrictedMovePathTool(
        root_directory=root_directory,
        project_directories=project_directories,
        allow_overwrite=allow_overwrite,
    )
    delete_tool = RestrictedDeletePathTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    patch_tool = RestrictedApplyTextPatchTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    hash_tool = RestrictedFileHashTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    info_tool = RestrictedPathInfoTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    mkdir_tool = RestrictedMakeDirectoryTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    copy_tool = RestrictedCopyPathTool(
        root_directory=root_directory,
        project_directories=project_directories,
        allow_overwrite=allow_overwrite,
    )
    read_json_tool = RestrictedReadJsonFileTool(
        root_directory=root_directory,
        project_directories=project_directories,
    )
    write_json_tool = RestrictedWriteJsonFileTool(
        root_directory=root_directory,
        project_directories=project_directories,
        allow_overwrite=allow_overwrite,
    )

    register.register(
        read_tool.definition,
        read_tool.executor(),
        preflight_policy=read_tool.preflight_policy(),
    )
    register.register(
        write_tool.definition,
        write_tool.executor(),
        preflight_policy=write_tool.preflight_policy(),
    )
    register.register(
        append_tool.definition,
        append_tool.executor(),
        preflight_policy=append_tool.preflight_policy(),
    )
    register.register(
        list_tool.definition,
        list_tool.executor(),
        preflight_policy=list_tool.preflight_policy(),
    )
    register.register(
        find_tool.definition,
        find_tool.executor(),
        preflight_policy=find_tool.preflight_policy(),
    )
    register.register(
        search_tool.definition,
        search_tool.executor(),
        preflight_policy=search_tool.preflight_policy(),
    )
    register.register(
        read_lines_tool.definition,
        read_lines_tool.executor(),
        preflight_policy=read_lines_tool.preflight_policy(),
    )
    register.register(
        move_tool.definition,
        move_tool.executor(),
        preflight_policy=move_tool.preflight_policy(),
    )
    register.register(
        delete_tool.definition,
        delete_tool.executor(),
        preflight_policy=delete_tool.preflight_policy(),
    )
    register.register(
        patch_tool.definition,
        patch_tool.executor(),
        preflight_policy=patch_tool.preflight_policy(),
    )
    register.register(
        hash_tool.definition,
        hash_tool.executor(),
        preflight_policy=hash_tool.preflight_policy(),
    )
    register.register(
        info_tool.definition,
        info_tool.executor(),
        preflight_policy=info_tool.preflight_policy(),
    )
    register.register(
        mkdir_tool.definition,
        mkdir_tool.executor(),
        preflight_policy=mkdir_tool.preflight_policy(),
    )
    register.register(
        copy_tool.definition,
        copy_tool.executor(),
        preflight_policy=copy_tool.preflight_policy(),
    )
    register.register(
        read_json_tool.definition,
        read_json_tool.executor(),
        preflight_policy=read_json_tool.preflight_policy(),
    )
    register.register(
        write_json_tool.definition,
        write_json_tool.executor(),
        preflight_policy=write_json_tool.preflight_policy(),
    )
