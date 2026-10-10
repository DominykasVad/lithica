from collections.abc import Callable
from typing import Any

from lithica import db, errors, model, rest
from lithica.func import scores, serialization, users, util


class InvalidCommentIdError(errors.ValidationError):
    pass


class CommentNotFoundError(errors.NotFoundError):
    pass


class EmptyCommentTextError(errors.ValidationError):
    pass


class CommentSerializer(serialization.BaseSerializer):
    def __init__(self, comment: model.Comment, auth_user: model.User) -> None:
        self.comment = comment
        self.auth_user = auth_user

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
        return self.comment.post.post_id

    def serialize_version(self) -> Any:
        return self.comment.version

    def serialize_text(self) -> Any:
        return self.comment.text

    def serialize_creation_time(self) -> Any:
        return self.comment.creation_time

    def serialize_last_edit_time(self) -> Any:
        return self.comment.last_edit_time

    def serialize_score(self) -> Any:
        return self.comment.score

    def serialize_own_score(self) -> Any:
        return scores.get_score(self.comment, self.auth_user)


def serialize_comment(
    comment: model.Comment, auth_user: model.User, options: list[str] | None = None
) -> rest.Response:
    if options is None:
        options = []
    if comment is None:
        return None
    return CommentSerializer(comment, auth_user).serialize(options)


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
