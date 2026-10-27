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
    Sends a confirmation email to given user. The email contains link containing
    a token. The token cannot be guessed, thus using such link proves that the
    person who requested to reset the password also owns the mailbox, which is a
    strong indication they are the rightful owner of the account.

    The token is random, works once and expires after the time set in
    `password_reset_token_lifetime` (one hour by default). Requesting another
    email makes the previous token stop working.

    Errors:

    - the user does not exist
    - the user hasn't provided an email address
    - the site cannot send mail (no mail server is set up): 500
      `MailNotConfiguredError`; `canSendMails` of `GET /info` says so ahead
    """
    user = users.get_user_by_name_or_email(user_name)
    if not user.email:
        raise errors.ValidationError(
            "User %r hasn't supplied email. Cannot reset password." % (user_name)
        )
    # before a token is made: a reset the site cannot mail leaves nothing
    mailer.verify_can_send_mail()
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
    """
    Generates a new password for given user. Password is sent as plain-text, so
    it is recommended to connect through HTTPS.

    Errors:

    - the token is missing
    - the token is invalid, expired or already used
    - the user does not exist
    """
    user = users.get_user_by_name_or_email(user_name)
    token = body.require("token")
    password_reset.consume_token(user, token)
    new_password = users.reset_user_password(user)
    versions.bump_version(user)
    db.session.commit()
    return {"password": new_password}
