from typing import Annotated, Any

from fastapi import Depends

from lithica import model
from lithica.api import resources
from lithica.api.dependencies import RequestDataParam, require
from lithica.api.routing import ApiRouter
from lithica.api.schemas import RequestModel, Str, optional, request_body
from lithica.func import auth, file_uploads

router = ApiRouter(tags=["Uploads"])


class TemporaryUpload(RequestModel):
    # where to fetch the content from, when it is not uploaded as a part
    content_url: Str = optional()


@router.post(
    "/uploads",
    response_model=resources.UploadToken,
    summary="Upload a temporary file",
    openapi_extra=request_body(TemporaryUpload, "content"),
)
def create_temporary_file(
    auth_user: Annotated[model.User, Depends(require("uploads:create"))],
    data: RequestDataParam,
) -> Any:
    """
    Store a file for a while and get a token for it. The token stands for
    the file in a later request (`contentToken`, `thumbnailToken`,
    `avatarToken`), so that a large file is sent once while its post is
    still being edited.
    """
    content = data.get_file(
        "content",
        allow_tokens=False,
        use_video_downloader=auth.has_privilege(auth_user, "uploads:use_downloader"),
    )
    token = file_uploads.save(content)
    return {"token": token}
