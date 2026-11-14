import base64
import binascii
import re
from typing import Annotated, Any

from fastapi import Depends

from lithica import errors, model
from lithica.api import resources
from lithica.api.dependencies import RequestDataParam, max_base64_upload_size, require
from lithica.api.error_handlers import HttpError
from lithica.api.routing import ApiRouter
from lithica.api.schemas import RequestModel, Str, optional, request_body
from lithica.func import auth, file_uploads

router = ApiRouter(tags=["Uploads"])


class TemporaryUpload(RequestModel):
    # where to fetch the content from, when it is not uploaded as a part
    content_url: Str = optional()
    content_base64: Str = optional()


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
    sources = sum(
        (
            "content" in data.files,
            "contentUrl" in data.params,
            "contentBase64" in data.params,
        )
    )
    if sources > 1:
        raise errors.ValidationError("Supply exactly one content source.")
    if "contentBase64" in data.params:
        encoded = data.params["contentBase64"]
        if (
            not isinstance(encoded, str)
            or re.fullmatch(
                r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?",
                encoded,
            )
            is None
        ):
            raise errors.ValidationError("Invalid standard padded base64 content.")
        decoded_size = len(encoded) // 4 * 3 - (len(encoded) - len(encoded.rstrip("=")))
        if decoded_size > max_base64_upload_size():
            raise HttpError(
                413,
                "RequestTooLargeError",
                "Decoded content exceeds its size limit.",
                title="Payload Too Large",
            )
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise errors.ValidationError(
                "Invalid standard padded base64 content."
            ) from None
        if not content:
            raise errors.MissingRequiredFileError("Required file 'content' is missing.")
        return {"token": file_uploads.save(content)}
    content = data.get_file(
        "content",
        allow_tokens=False,
        use_video_downloader=auth.has_privilege(auth_user, "uploads:use_downloader"),
    )
    token = file_uploads.save(content)
    return {"token": token}
