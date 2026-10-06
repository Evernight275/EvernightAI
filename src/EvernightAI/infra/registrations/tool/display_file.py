from pathlib import Path

from EvernightAI.core.protocol.file import FileArtifactStoreProtocol
from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.schema.file import DisplayFileRequest
from EvernightAI.core.schema.tool import ToolDefinition, ToolPermission
from EvernightAI.infra.adapters.tool.display_file import DisplayFileTool


def register_display_file_tool(
    register: ToolRegisterProtocol,
    *,
    root_directory: str | Path,
    store: FileArtifactStoreProtocol,
    workspace_directories: WorkspaceDirectoryProtocol | None = None,
) -> None:
    adapter = DisplayFileTool(
        root_directory=root_directory,
        store=store,
        workspace_directories=workspace_directories,
    )
    register.register(
        ToolDefinition(
            name="display_file",
            description="Display an existing file to the user in the chat and offer a download. Use after creating a matplotlib plot, screenshot, HTML visualization, document, or other file. PNG, JPEG, GIF and WebP images get inline previews. HTML pages run CSS and JavaScript in an isolated preview. For HTML, embed data and local assets in the file; absolute HTTPS script, style and image URLs are supported, but relative companion files, network data requests and form submissions are unavailable. Other files are downloadable. Paths must be inside the current working directory, up to 20 MiB. Saves a snapshot for chat history. Returns a file reference, never file content or Base64. This tool does not generate files.",
            parameters_schema=DisplayFileRequest.model_json_schema(),
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            metadata={
                "supports_working_directory": True,
                "supports_execution_context": True,
            },
        ),
        adapter.execute,
        preflight_policy=adapter.preflight,
    )
