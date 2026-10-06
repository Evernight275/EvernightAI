from urllib.parse import quote

from fastapi import APIRouter, Response

from EvernightAI.core.schema.file import FileArtifactInfo
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/files", tags=["files"])


@router.get(
    "/{artifact_id}", response_model=FileArtifactInfo, operation_id="get_file_artifact"
)
def get_file(
    artifact_id: str, interface: InterfaceDependency, response: Response
) -> FileArtifactInfo:
    response.headers["Cache-Control"] = "private, no-store"
    return interface.files.get_file(artifact_id)


@router.get(
    "/{artifact_id}/content", operation_id="read_file_artifact", response_class=Response
)
def read_file(
    artifact_id: str, interface: InterfaceDependency, download: bool = False
) -> Response:
    info, content = interface.files.read_file(artifact_id)
    inline = info.preview_kind == "image" and not download
    return Response(
        content,
        media_type=info.mime_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename=\"download\"; filename*=UTF-8''{quote(info.name, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
