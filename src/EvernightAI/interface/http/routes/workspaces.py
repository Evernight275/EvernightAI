from typing import cast

from fastapi import APIRouter, Request

from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import require_permission
from EvernightAI.core.error.base import UnsupportedError
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.workspace import WorkspaceDirectory
from EvernightAI.interface.http.protocol import HttpAuthDeviceProtocol


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class CreateDirectoryRequest(EvernightAISchema):
    path: str = "."
    name: str


def directory_store(request: Request, action: str) -> WorkspaceDirectoryProtocol:
    device = cast(HttpAuthDeviceProtocol | None, request.app.state.auth_device)
    if device is not None:
        require_permission(
            Authorizer(PermissionAuthPolicy()),
            device.principal_for_request(request),
            "workspaces",
            action,
        )
    store = cast(
        WorkspaceDirectoryProtocol | None, request.app.state.workspace_directories
    )
    if store is None:
        raise UnsupportedError("服务未启用文件工作目录，请先配置文件工具根目录")
    return store


@router.get("", response_model=WorkspaceDirectory)
def browse_directories(request: Request, path: str = ".") -> WorkspaceDirectory:
    return directory_store(request, "list").browse(path)


@router.post("", response_model=WorkspaceDirectory, status_code=201)
def create_directory(
    body: CreateDirectoryRequest, request: Request
) -> WorkspaceDirectory:
    return directory_store(request, "create").create(body.path, body.name)
