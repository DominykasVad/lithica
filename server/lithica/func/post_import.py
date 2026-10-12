"""
Bulk import: a post per file of a folder, for `lithica-admin import`.

A file goes the way an upload goes (lithica.api.post_api.create_post): the
same checks, the same thumbnails and signatures, the modules' extractors
and automatic tags, a snapshot in the history. What an upload has and an
import has not is a request: nobody's privileges are asked, since the
command is run by whoever administers the site.

Every file is a unit of work of its own, committed or rolled back before
the next one starts, so a file that cannot be imported costs that file and
an interrupted run leaves whole posts behind. A file that is a post
already (the same checksum) is skipped, which is what makes a run safe to
repeat.
"""

import logging
import os
from dataclasses import dataclass, field

from lithica import db, errors, model
from lithica.func import (
    file_types,
    post_content,
    posts,
    snapshots,
    tags,
    users,
    util,
)
from lithica.func.content import Content

logger = logging.getLogger(__name__)

CREATED = "created"
SKIPPED = "skipped"
REFUSED = "refused"
FAILED = "failed"


@dataclass
class Outcome:
    """What became of one file. `detail` says why, for all but the created."""

    path: str
    status: str
    detail: str = ""
    post_id: int | None = None


@dataclass
class ImportResult:
    outcomes: list[Outcome] = field(default_factory=list[Outcome])

    def count(self, status: str) -> int:
        return len([outcome for outcome in self.outcomes if outcome.status == status])

    @property
    def problems(self) -> list[Outcome]:
        """The files that are not posts now and should have been looked at."""
        return [
            outcome for outcome in self.outcomes if outcome.status in (REFUSED, FAILED)
        ]


def find_files(folder: str) -> list[str]:
    """
    The files of a folder and of the folders in it, as paths relative to it,
    sorted, so that two runs go through them in the same order. Files and
    folders whose names start with a dot are left out: they are what file
    managers and version control leave behind, not part of a collection.
    """
    found: list[str] = []
    for directory, subdirectories, names in os.walk(folder):
        subdirectories[:] = sorted(
            name for name in subdirectories if not name.startswith(".")
        )
        for name in names:
            path = os.path.join(directory, name)
            if not name.startswith(".") and os.path.isfile(path):
                found.append(os.path.relpath(path, folder))
    return sorted(found)


def verify_tag_names(tag_names: list[str]) -> None:
    """Refuse the tags of an import before the first file, not at each one."""
    for name in tag_names:
        if not tags.is_valid_name(name):
            raise tags.InvalidTagNameError("%r is not a valid tag name." % name)


def _create_post(
    content: Content, user: model.User, safety: str, tag_names: list[str]
) -> model.Post:
    """The steps of an upload, in the order the API takes them."""
    flags = posts.get_default_flags(content)
    post, new_tags = posts.create_post(content, tag_names, user)
    posts.update_post_safety(post, safety)
    posts.update_post_flags(post, flags)
    new_tags = new_tags + posts.update_post_auto_tags(post)
    db.session.add(post)
    db.session.flush()
    snapshots.create(post, user)
    for tag in new_tags:
        snapshots.create(tag, user)
    # what the site makes of an animation besides the animation itself
    for alternate_post, alternate_tags in posts.generate_alternate_formats(
        post, content
    ):
        snapshots.create(alternate_post, user)
        for tag in alternate_tags:
            snapshots.create(tag, user)
    return post


def _import_file(
    path: str, content: Content, user_name: str, safety: str, tag_names: list[str]
) -> Outcome:
    try:
        if not content:
            # as the upload path says it, which asks before it looks
            return Outcome(path, REFUSED, "Post content missing.")
        # read anew for every file: the last one may have ended in a rollback
        user = users.get_user_by_name(user_name)
        post = _create_post(content, user, safety, tag_names)
        post_id = post.post_id
        db.session.commit()
    except posts.PostAlreadyUploadedError as ex:
        db.session.rollback()
        return Outcome(path, SKIPPED, str(ex))
    except (errors.ValidationError, errors.ProcessingError) as ex:
        # the file's own fault: a type nobody knows, a broken picture, a
        # file a module refuses
        db.session.rollback()
        return Outcome(path, REFUSED, str(ex))
    except Exception as ex:
        db.session.rollback()
        logger.exception("Could not import %s", path)
        return Outcome(path, FAILED, "%s: %s" % (type(ex).__name__, ex))
    return Outcome(path, CREATED, post_id=post_id)


def _examine_file(path: str, content: Content, seen: dict[str, str]) -> Outcome:
    """
    What an import would make of a file, as far as that can be told without
    making the post: whether it is a post already, whether anybody knows
    its type, whether a module refuses it. A picture that turns out to be
    broken when it is processed is found by the import only.
    """
    try:
        if not content:
            return Outcome(path, REFUSED, "Post content missing.")
        checksum = util.get_sha1(content)
        if checksum in seen:
            return Outcome(path, SKIPPED, "The same file as %s" % seen[checksum])
        seen[checksum] = path
        existing = posts.search_by_image_exact(content)
        if existing is not None:
            return Outcome(
                path, SKIPPED, "Post already uploaded (%d)" % existing.post_id
            )
        # the engine's answer, or a module's for a file the engine does not know
        mime_type = file_types.get_mime_type(content)
        if mime_type == "application/octet-stream":
            return Outcome(path, REFUSED, "Unhandled file type: %r" % mime_type)
        rejections = post_content.extract(mime_type, content).rejections
        if rejections:
            return Outcome(path, REFUSED, rejections[0])
    except errors.ValidationError as ex:
        return Outcome(path, REFUSED, str(ex))
    except Exception as ex:
        logger.exception("Could not read %s", path)
        return Outcome(path, FAILED, "%s: %s" % (type(ex).__name__, ex))
    return Outcome(path, CREATED)


def import_folder(
    folder: str,
    user_name: str,
    safety: str,
    tag_names: list[str],
    dry_run: bool = False,
) -> ImportResult:
    """
    Make a post of every file in the folder, as this user, with this safety
    and these tags. With `dry_run` nothing is made and the result says what
    would be (see _examine_file for how far that goes).

    Raises before the first file for a user, a safety or a tag that cannot
    be: UserNotFoundError, InvalidPostSafetyError, InvalidTagNameError.
    """
    users.get_user_by_name(user_name)
    posts.update_post_safety(model.Post(), safety)
    verify_tag_names(tag_names)

    result = ImportResult()
    seen: dict[str, str] = {}
    for path in find_files(folder):
        # the file stays where it is: storing it copies it
        content = Content(os.path.join(folder, path))
        if dry_run:
            outcome = _examine_file(path, content, seen)
        else:
            outcome = _import_file(path, content, user_name, safety, tag_names)
        result.outcomes.append(outcome)
        if outcome.status != CREATED:
            logger.info("%s %s%s", outcome.status, path, _reason(outcome))
        elif dry_run:
            logger.info("would create a post from %s", path)
        else:
            logger.info("created post %d from %s", outcome.post_id, path)
    return result


def _reason(outcome: Outcome) -> str:
    return ": " + outcome.detail if outcome.detail else ""
