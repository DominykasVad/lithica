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
    Puts a file in temporary storage and assigns it a token that can be used in
    other requests. The files uploaded that way are deleted after a short while
    so clients shouldn't use it as a free upload service.

    Errors:

    - privileges are too low
    """
    content = data.get_file(
        "content",
        allow_tokens=False,
        use_video_downloader=auth.has_privilege(auth_user, "uploads:use_downloader"),
    )
    token = file_uploads.save(content)
    return {"token": token}
