from datetime import datetime

from lithica import db
from lithica.func import auth


def test_saving_user_token(user_token_factory):
    user_token = user_token_factory(token="dummy")
    db.session.add(user_token)
    db.session.flush()
    db.session.refresh(user_token)
    assert not db.session.dirty
    assert user_token.user is not None
    assert user_token.token_hash == auth.hash_token("dummy")
    assert user_token.kind == "login"
    assert user_token.rights is None
    assert user_token.enabled is True
    assert user_token.creation_time == datetime(1997, 1, 1)
