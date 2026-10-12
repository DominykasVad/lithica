"""
The proof module: the smallest module that uses every part of the module
system the engine has. It exists for the tests, and as the example to copy
when writing a real one.

It reads the text chunks (`tEXt`) of PNG files. Each chunk is a keyword and
a text; the module keeps them as content of the kind `dummy_v1`, tags posts
from them, makes the text searchable and counts the posts that have any.
"""

import struct
from collections.abc import Iterator, Mapping, Sequence
from typing import Annotated, Any, BinaryIO

import sqlalchemy as sa
from fastapi import Depends

from lithica import db, model, registry
from lithica.api.dependencies import require
from lithica.api.routing import ApiRouter
from lithica.search.configs import util as search_util

KIND = "dummy_v1"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# a text chunk larger than this is not read: the file is somebody's upload
MAX_TEXT_SIZE = 64 * 1024

# the keyword whose text becomes a tag of the post
TAG_KEYWORD = "Tag"


def _text_chunks(handle: BinaryIO) -> Iterator[tuple[str, str]]:
    """The (keyword, text) of every tEXt chunk of a PNG file."""
    if handle.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
        return
    while True:
        header = handle.read(8)
        if len(header) < 8:
            return
        length: int
        chunk_type: bytes
        length, chunk_type = struct.unpack(">I4s", header)
        if chunk_type == b"IEND":
            return
        if chunk_type != b"tEXt" or length > MAX_TEXT_SIZE:
            # past the data and its checksum
            handle.seek(length + 4, 1)
            continue
        data = handle.read(length)
        if len(data) < length:
            # the file ends inside the chunk
            return
        handle.seek(4, 1)
        keyword, separator, text = data.partition(b"\x00")
        if separator:
            # the PNG specification says Latin-1; NUL cannot be stored
            yield (
                keyword.decode("latin-1"),
                text.decode("latin-1").replace("\x00", " "),
            )


def extract(_mime_type: str, handle: BinaryIO) -> Iterator[registry.ExtractedContent]:
    for keyword, text in _text_chunks(handle):
        yield registry.ExtractedContent(KIND, {"keyword": keyword, "text": text})


def auto_tag(contents: Sequence[registry.ExtractedContent]) -> Mapping[str, list[str]]:
    names = [
        str(content.payload["text"])
        for content in contents
        if content.payload["keyword"] == TAG_KEYWORD
    ]
    return {"meta": ["dummy_text", *names]}


def _keywords(post: model.Post, _user: model.User) -> list[str]:
    """The post field `dummyKeywords`: the keywords of the post's text chunks."""
    return sorted({row.payload["keyword"] for row in post.contents if row.kind == KIND})


def _print_count(_arguments: Any) -> int:
    count = (
        db.session.query(model.PostContent)
        .filter(model.PostContent.kind == KIND)
        .count()
    )
    # the admin CLI talks to a terminal
    print("dummy: %d text chunks" % count)  # noqa: T201
    return 0


router = ApiRouter()


@router.get("/stats", summary="Count the posts that have text chunks")
def get_stats(
    _auth_user: Annotated[model.User, Depends(require("posts:list"))],
) -> dict[str, int]:
    """Says how many posts have text chunks, and how many chunks there are."""
    posts, chunks = (
        db.session.query(
            sa.func.count(sa.distinct(model.PostContent.post_id)),
            sa.func.count(model.PostContent.post_content_id),
        )
        .filter(model.PostContent.kind == KIND)
        .one()
    )
    return {"posts": posts, "chunks": chunks}


module = registry.Module(
    name="dummy",
    router=router,
    content_kinds=[registry.ContentKind(KIND)],
    extractors=[registry.Extractor(frozenset({"image/png"}), extract)],
    auto_tag=auto_tag,
    search_filters={
        # dummy-text:<pattern> finds posts by the text of their chunks
        "dummy-text": search_util.create_subquery_filter(
            model.Post.post_id,
            model.PostContent.post_id,
            model.PostContent.payload["text"].as_string(),
            search_util.create_str_filter,
            lambda subquery: subquery.filter(model.PostContent.kind == KIND),
        )
    },
    post_fields={"dummyKeywords": _keywords},
    admin_commands=[
        registry.AdminCommand(
            "dummy-count", "count the text chunks the dummy module stored", _print_count
        )
    ],
)
