from typing import Any


class BaseError(RuntimeError):
    def __init__(
        self,
        message: str = "Unknown error",
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.extra_fields = extra_fields


class ConfigError(BaseError):
    pass


class AuthError(BaseError):
    pass


class InvalidTokenError(AuthError):
    """
    The login token a request carries does not work: unknown, disabled,
    expired, or of a user who does not exist. Named apart from a missing
    privilege, so that a client knows its session is over without reading
    the description.
    """


class IntegrityError(BaseError):
    pass


class ValidationError(BaseError):
    pass


class SearchError(BaseError):
    pass


class NotFoundError(BaseError):
    pass


class ProcessingError(BaseError):
    pass


class MissingRequiredFileError(ValidationError):
    pass


class MissingOrExpiredRequiredFileError(MissingRequiredFileError):
    pass


class MissingRequiredParameterError(ValidationError):
    pass


class InvalidParameterError(ValidationError):
    pass


class ThirdPartyError(BaseError):
    pass
