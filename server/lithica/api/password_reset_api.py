from lithica import config, errors, rest
from lithica.func import mailer, password_reset, users, versions

MAIL_SUBJECT = "Password reset for {name}"
MAIL_BODY = (
    "You (or someone else) requested to reset your password on {name}.\n"
    "If you wish to proceed, click this link: {url}\n"
    "Otherwise, please ignore this email."
)


@rest.routes.get("/password-reset/(?P<user_name>[^/]+)/?")
def start_password_reset(ctx: rest.Context, params: dict[str, str]) -> rest.Response:
    user_name = params["user_name"]
    user = users.get_user_by_name_or_email(user_name)
    if not user.email:
        raise errors.ValidationError(
            "User %r hasn't supplied email. Cannot reset password." % (user_name)
        )
    token = password_reset.create_token(user)

    if config.config["domain"]:
        url = config.config["domain"]
    elif "HTTP_ORIGIN" in ctx.env:
        url = ctx.env["HTTP_ORIGIN"].rstrip("/")
    elif "HTTP_REFERER" in ctx.env:
        url = ctx.env["HTTP_REFERER"].rstrip("/")
    else:
        url = ""
    url += "/password-reset/%s:%s" % (user.name, token)

    mailer.send_mail(
        config.config["smtp"]["from"],
        user.email,
        MAIL_SUBJECT.format(name=config.config["name"]),
        MAIL_BODY.format(name=config.config["name"], url=url),
    )
    ctx.session.commit()

    return {}


@rest.routes.post("/password-reset/(?P<user_name>[^/]+)/?")
def finish_password_reset(ctx: rest.Context, params: dict[str, str]) -> rest.Response:
    user_name = params["user_name"]
    user = users.get_user_by_name_or_email(user_name)
    token = ctx.get_param_as_string("token")
    password_reset.consume_token(user, token)
    new_password = users.reset_user_password(user)
    versions.bump_version(user)
    ctx.session.commit()
    return {"password": new_password}
