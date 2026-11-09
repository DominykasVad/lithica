from collections.abc import Callable, Sequence
from typing import Any, cast

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica import db, errors, model
from lithica.func import scores, serialization, users, util


class InvalidCommentIdError(errors.ValidationError):
    pass


class CommentNotFoundError(errors.NotFoundError):
    pass


class EmptyCommentTextError(errors.ValidationError):
    pass


class CommentSerializer(serialization.BaseSerializer):
    """
    A comment. `scores` and `own_scores` (comment id -> the sum of its
    scores, and the requesting user's score), when given, are the scores of
    a page of comments loaded at once; without them each is asked for.
    """

    def __init__(
        self,
        comment: model.Comment,
        auth_user: model.User,
        scores: dict[int, int] | None = None,
        own_scores: dict[int, int] | None = None,
    ) -> None:
        self.comment = comment
        self.auth_user = auth_user
        self.scores = scores
        self.own_scores = own_scores

    def _serializers(self) -> dict[str, Callable[[], Any]]:
        return {
            "id": self.serialize_id,
            "user": self.serialize_user,
            "postId": self.serialize_post_id,
            "version": self.serialize_version,
            "text": self.serialize_text,
            "creationTime": self.serialize_creation_time,
            "lastEditTime": self.serialize_last_edit_time,
            "score": self.serialize_score,
            "ownScore": self.serialize_own_score,
        }

    def serialize_id(self) -> Any:
        return self.comment.comment_id

    def serialize_user(self) -> Any:
        return users.serialize_micro_user(self.comment.user, self.auth_user)

    def serialize_post_id(self) -> Any:
        # the column: the post itself need not be loaded for its id
        return self.comment.post_id

    def serialize_version(self) -> Any:
        return self.comment.version

    def serialize_text(self) -> Any:
        return self.comment.text

    def serialize_creation_time(self) -> Any:
        return self.comment.creation_time

    def serialize_last_edit_time(self) -> Any:
        return self.comment.last_edit_time

    def serialize_score(self) -> Any:
        if self.scores is not None:
            return self.scores.get(self.comment.comment_id, 0)
        return self.comment.score

    def serialize_own_score(self) -> Any:
        if self.own_scores is not None:
            return self.own_scores.get(self.comment.comment_id, 0)
        return scores.get_score(self.comment, self.auth_user)


def serialize_comment(
    comment: model.Comment,
    auth_user: model.User,
    options: list[str] | None = None,
    scores: dict[int, int] | None = None,
    own_scores: dict[int, int] | None = None,
) -> serialization.Response:
    if options is None:
        options = []
    if comment is None:
        return None
    return CommentSerializer(comment, auth_user, scores, own_scores).serialize(options)


def serialize_comments(
    found: Sequence[model.Comment],
    auth_user: model.User,
    options: list[str] | None = None,
) -> list[serialization.Response]:
    """
    Comments, as `serialize_comment` gives each: their users and scores are
    loaded for all of them at once (`load_comment_scores`).
    """
    options = options or []
    # only the names are read: no comment is needed to list them
    every = CommentSerializer(cast(model.Comment, None), auth_user)._serializers()
    fields = set(options) or set(every)
    ids = sorted({comment.comment_id for comment in found})
    if ids and "user" in fields:
        db.session.query(model.Comment).filter(
            model.Comment.comment_id.in_(ids)
        ).options(
            sa_orm.lazyload("*"),
            sa_orm.load_only(model.Comment.comment_id),
            sa_orm.selectinload(model.Comment.user).options(sa_orm.lazyload("*")),
        ).all()
    sums, own = load_comment_scores(ids, auth_user)
    return [
        serialize_comment(
            comment,
            auth_user,
            options,
            scores=sums if "score" in fields else None,
            own_scores=own if "ownScore" in fields else None,
        )
        for comment in found
    ]


def load_comment_scores(
    comment_ids: Sequence[int], auth_user: model.User
) -> tuple[dict[int, int], dict[int, int]]:
    """
    For these comments, at once: comment id -> the sum of its scores, and
    comment id -> the requesting user's score (absent: 0, for both).
    """
    if not comment_ids:
        return {}, {}
    score = model.CommentScore
    sums = db.session.execute(
        sa.select(score.comment_id, sa.func.sum(score.score))
        .where(score.comment_id.in_(comment_ids))
        .group_by(score.comment_id)
    )
    totals = {key: total or 0 for key, total in sums}
    own: dict[int, int] = {}
    if auth_user.user_id is not None:
        rows = db.session.execute(
            sa.select(score.comment_id, score.score)
            .where(score.user_id == auth_user.user_id)
            .where(score.comment_id.in_(comment_ids))
        )
        own = {key: value for key, value in rows}
    return totals, own


def try_get_comment_by_id(comment_id: int) -> model.Comment | None:
    comment_id = int(comment_id)
    return (
        db.session.query(model.Comment)
        .filter(model.Comment.comment_id == comment_id)
        .one_or_none()
    )


def get_comment_by_id(comment_id: int) -> model.Comment:
    comment = try_get_comment_by_id(comment_id)
    if comment:
        return comment
    raise CommentNotFoundError("Comment %r not found." % comment_id)


def create_comment(
    user: model.User | None, post: model.Post, text: str
) -> model.Comment:
    comment = model.Comment()
    comment.user = user
    comment.post = post
    update_comment_text(comment, text)
    comment.creation_time = util.utcnow()
    return comment


def update_comment_text(comment: model.Comment, text: str) -> None:
    assert comment
    if not text:
        raise EmptyCommentTextError("Comment text cannot be empty.")
    comment.text = text
