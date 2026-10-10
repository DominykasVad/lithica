import threading
from typing import Any

import sqlalchemy as sa
import sqlalchemy.orm

from lithica import config

_data = threading.local()
_engine: Any = sa.create_engine(config.config["database"])
_sessionmaker: Any = sa.orm.sessionmaker(_engine, autoflush=False)
session: Any = sa.orm.scoped_session(_sessionmaker)


def get_session() -> Any:
    global session
    return session


def set_sesssion(new_session: Any) -> None:
    global session
    session = new_session


def reset_query_count() -> None:
    _data.query_count = 0


def get_query_count() -> int:
    return _data.query_count


def _bump_query_count() -> None:
    _data.query_count = getattr(_data, "query_count", 0) + 1


sa.event.listen(_engine, "after_execute", lambda *args: _bump_query_count())
