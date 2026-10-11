"""
What is left of the old application's entry point: its error handlers. The
old WSGI application is mounted in lithica.app until every route is ported.
"""

import sqlalchemy.orm as sa_orm

# api and middleware are imported for their side effects: they register the
# routes and the request hooks
from lithica import api, errors, middleware, rest  # noqa: F401


def _map_error(
    ex: Exception, target_class: type[rest.errors.BaseHttpError], title: str
) -> rest.errors.BaseHttpError:
    return target_class(
        name=type(ex).__name__,
        title=title,
        description=str(ex),
        extra_fields=getattr(ex, "extra_fields", {}),
    )


def _on_auth_error(ex: Exception) -> None:
    raise _map_error(ex, rest.errors.HttpForbidden, "Authentication error")


def _on_validation_error(ex: Exception) -> None:
    raise _map_error(ex, rest.errors.HttpBadRequest, "Validation error")


def _on_search_error(ex: Exception) -> None:
    raise _map_error(ex, rest.errors.HttpBadRequest, "Search error")


def _on_integrity_error(ex: Exception) -> None:
    raise _map_error(ex, rest.errors.HttpConflict, "Integrity violation")


def _on_not_found_error(ex: Exception) -> None:
    raise _map_error(ex, rest.errors.HttpNotFound, "Not found")


def _on_processing_error(ex: Exception) -> None:
    raise _map_error(ex, rest.errors.HttpBadRequest, "Processing error")


def _on_third_party_error(ex: Exception) -> None:
    raise _map_error(
        ex, rest.errors.HttpInternalServerError, "Server configuration error"
    )


def _on_stale_data_error(_ex: Exception) -> None:
    raise rest.errors.HttpConflict(
        name="IntegrityError",
        title="Integrity violation",
        description=("Someone else modified this in the meantime. Please try again."),
    )


def register_error_handlers() -> None:
    rest.errors.handle(errors.AuthError, _on_auth_error)
    rest.errors.handle(errors.ValidationError, _on_validation_error)
    rest.errors.handle(errors.SearchError, _on_search_error)
    rest.errors.handle(errors.IntegrityError, _on_integrity_error)
    rest.errors.handle(errors.NotFoundError, _on_not_found_error)
    rest.errors.handle(errors.ProcessingError, _on_processing_error)
    rest.errors.handle(errors.ThirdPartyError, _on_third_party_error)
    rest.errors.handle(sa_orm.exc.StaleDataError, _on_stale_data_error)
