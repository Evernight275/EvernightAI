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
) -> None:
    read_tool = RestrictedReadTextFileTool(
        root_directory=root_directory,
        max_chars=max_read_chars,
    )
    write_tool = RestrictedWriteTextFileTool(
        root_directory=root_directory,
        allow_overwrite=allow_overwrite,
    )
    append_tool = RestrictedAppendTextFileTool(root_directory=root_directory)
    list_tool = RestrictedListDirectoryTool(
        root_directory=root_directory,
        max_entries=max_directory_entries,
    )
    find_tool = RestrictedFindPathsTool(
        root_directory=root_directory,
        max_results=max_search_results,
    )
    search_tool = RestrictedSearchTextFilesTool(
        root_directory=root_directory,
        max_results=max_search_results,
    )
    read_lines_tool = RestrictedReadTextFileLinesTool(root_directory=root_directory)
    move_tool = RestrictedMovePathTool(
        root_directory=root_directory,
        allow_overwrite=allow_overwrite,
    )
    delete_tool = RestrictedDeletePathTool(root_directory=root_directory)
    patch_tool = RestrictedApplyTextPatchTool(root_directory=root_directory)
    hash_tool = RestrictedFileHashTool(root_directory=root_directory)
    info_tool = RestrictedPathInfoTool(root_directory=root_directory)
    mkdir_tool = RestrictedMakeDirectoryTool(root_directory=root_directory)
    copy_tool = RestrictedCopyPathTool(
        root_directory=root_directory,
        allow_overwrite=allow_overwrite,
    )
    read_json_tool = RestrictedReadJsonFileTool(root_directory=root_directory)
    write_json_tool = RestrictedWriteJsonFileTool(
        root_directory=root_directory,
        allow_overwrite=allow_overwrite,
    )

    register.register(read_tool.definition, read_tool.executor())
    register.register(write_tool.definition, write_tool.executor())
    register.register(append_tool.definition, append_tool.executor())
    register.register(list_tool.definition, list_tool.executor())
    register.register(find_tool.definition, find_tool.executor())
    register.register(search_tool.definition, search_tool.executor())
    register.register(read_lines_tool.definition, read_lines_tool.executor())
    register.register(move_tool.definition, move_tool.executor())
    register.register(delete_tool.definition, delete_tool.executor())
    register.register(patch_tool.definition, patch_tool.executor())
    register.register(hash_tool.definition, hash_tool.executor())
    register.register(info_tool.definition, info_tool.executor())
    register.register(mkdir_tool.definition, mkdir_tool.executor())
    register.register(copy_tool.definition, copy_tool.executor())
    register.register(read_json_tool.definition, read_json_tool.executor())
    register.register(write_json_tool.definition, write_json_tool.executor())
