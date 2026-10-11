from typing import Annotated, Any

from fastapi import Depends

from lithica import config, db, errors
from lithica.api import resources
from lithica.api.dependencies import read_body
from lithica.api.routing import ApiRouter
from lithica.api.schemas import RequestModel, Str, request_body, required
from lithica.func import mailer, password_reset, users, versions

router = ApiRouter(tags=["Password reset"])

MAIL_SUBJECT = "Password reset for {name}"
MAIL_BODY = (
    "You (or someone else) requested to reset your password on {name}.\n"
    "If you wish to proceed, click this link: {url}\n"
    "Otherwise, please ignore this email."
)


class PasswordResetConfirmation(RequestModel):
    token: Str = required()


@router.get(
    "/password-reset/{user_name}",
    response_model=resources.Empty,
    summary="Request a password reset",
)
def start_password_reset(user_name: str) -> Any:
    """
    Mail a reset link to the user, who is named by user name or e-mail
    address. The link carries a token that works once and expires.
    """
    user = users.get_user_by_name_or_email(user_name)
    if not user.email:
        raise errors.ValidationError(
            "User %r hasn't supplied email. Cannot reset password." % (user_name)
        )
    token = password_reset.create_token(user)

    # The link is built from the configured domain only. Origin and Referer
    # come from whoever sends the request, and a link built from them would
    # mail the user a valid token pointing at the sender's own host.
    url = "%s/password-reset/%s:%s" % (
        (config.config["domain"] or "").rstrip("/"),
        user.name,
        token,
    )

    mailer.send_mail(
        config.config["smtp"]["from"],
        user.email,
        MAIL_SUBJECT.format(name=config.config["name"]),
        MAIL_BODY.format(name=config.config["name"], url=url),
    )
    db.session.commit()

    return {}


@router.post(
    "/password-reset/{user_name}",
    response_model=resources.PasswordResetResult,
    summary="Confirm a password reset",
    openapi_extra=request_body(PasswordResetConfirmation),
)
def finish_password_reset(
    user_name: str,
    body: Annotated[
        PasswordResetConfirmation, Depends(read_body(PasswordResetConfirmation))
    ],
) -> Any:
    """Trade the token from the mail for a new, generated password."""
    user = users.get_user_by_name_or_email(user_name)
    token = body.require("token")
    password_reset.consume_token(user, token)
    new_password = users.reset_user_password(user)
    versions.bump_version(user)
    db.session.commit()
    return {"password": new_password}
