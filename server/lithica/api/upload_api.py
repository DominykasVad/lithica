from lithica import rest
from lithica.func import auth, file_uploads


@rest.routes.post("/uploads/?")
def create_temporary_file(
    ctx: rest.Context, _params: dict[str, str] | None = None
) -> rest.Response:
    if _params is None:
        _params = {}
    auth.verify_privilege(ctx.user, "uploads:create")
    content = ctx.get_file(
        "content",
        allow_tokens=False,
        use_video_downloader=auth.has_privilege(ctx.user, "uploads:use_downloader"),
    )
    token = file_uploads.save(content)
    return {"token": token}
