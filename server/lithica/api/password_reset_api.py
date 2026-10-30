import logging
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends

from lithica import config, db
from lithica.api import resources
from lithica.api.dependencies import read_body
from lithica.api.routing import ApiRouter
from lithica.api.schemas import RequestModel, Str, request_body, required
from lithica.func import mailer, password_reset, users, versions

logger = logging.getLogger(__name__)

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
def start_password_reset(user_name: str, background: BackgroundTasks) -> Any:
    """
    Sends a confirmation email to given user. The email contains link containing
    a token. The token cannot be guessed, thus using such link proves that the
    person who requested to reset the password also owns the mailbox, which is a
    strong indication they are the rightful owner of the account.

    The token is random, works once and expires after the time set in
    `password_reset_token_lifetime` (one hour by default). Requesting another
    email makes the previous token stop working.

    The answer is the same 200 `{}` whether the account exists, has an email
    or not, and whether a mail was sent: it does not tell who has an account
    on the site. The mail goes out after the answer. An account is sent at
    most one mail per `password_reset_mail_interval` (five minutes by
    default); a request sooner sends nothing and leaves the link already
    sent working.

    Errors:

    - the site cannot send mail (no mail server is set up): 500
      `MailNotConfiguredError`; `canSendMails` of `GET /info` says so ahead
    """
    # first, for any name: that the site sends no mail is the site's to say,
    # and says nothing about the account
    mailer.verify_can_send_mail()
    user = users.try_get_user_by_name_or_email(user_name)
    if not user or not user.email or password_reset.mailed_recently(user):
        return {}
    token = password_reset.create_token(user)

    # The link is built from the configured domain only. Origin and Referer
    # come from whoever sends the request, and a link built from them would
    # mail the user a valid token pointing at the sender's own host.
    url = "%s/password-reset/%s:%s" % (
        (config.config["domain"] or "").rstrip("/"),
        user.name,
        token,
    )
    recipient = user.email
    db.session.commit()

    # after the answer: an account that gets a mail is answered as soon as
    # one that does not
    background.add_task(
        _send_reset_mail,
        recipient,
        MAIL_SUBJECT.format(name=config.config["name"]),
        MAIL_BODY.format(name=config.config["name"], url=url),
    )
    return {}


def _send_reset_mail(recipient: str, subject: str, body: str) -> None:
    try:
        mailer.send_mail(config.config["smtp"]["from"], recipient, subject, body)
    except Exception as e:
        # the requester was answered already. Only the kind of failure is
        # logged: the mail holds the link, and an SMTP error may hold the
        # recipient's address
        logger.error("A password reset mail could not be sent: %s", type(e).__name__)


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
