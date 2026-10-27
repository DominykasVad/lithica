import email.mime.text
import smtplib

from lithica import config, errors


class MailNotConfiguredError(errors.ThirdPartyError):
    """The site has no mail server set up (`smtp.host`): it sends no mail."""


def can_send_mail() -> bool:
    return bool(config.config["smtp"].get("host"))


def verify_can_send_mail() -> None:
    if not can_send_mail():
        raise MailNotConfiguredError(
            "This site cannot send mail: no mail server is set up in its "
            "configuration. Ask the site's administrator to reset the password."
        )


def send_mail(sender: str, recipient: str, subject: str, body: str) -> None:
    verify_can_send_mail()
    msg = email.mime.text.MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    smtp = smtplib.SMTP(
        config.config["smtp"]["host"], int(config.config["smtp"]["port"])
    )
    try:
        smtp.starttls()
    except smtplib.SMTPNotSupportedError:
        pass
    smtp.login(config.config["smtp"]["user"], config.config["smtp"]["pass"])
    smtp.send_message(msg)
    smtp.quit()
