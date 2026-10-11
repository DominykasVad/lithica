import os
from typing import Any

from lithica import config
from lithica.func import content as content_module
from lithica.func.content import Content, ContentLike


def _get_full_path(path: str) -> str:
    return os.path.join(config.config["data_dir"], path)


def delete(path: str) -> None:
    # No "does it exist" check first: another thread or server process may
    # delete the same file between the check and the unlink.
    try:
        os.unlink(_get_full_path(path))
    except FileNotFoundError:
        pass


def has(path: str) -> bool:
    return os.path.exists(_get_full_path(path))


def scan(path: str) -> list[Any]:
    if has(path):
        return list(os.scandir(_get_full_path(path)))
    return []


def move(source_path: str, target_path: str) -> None:
    os.rename(_get_full_path(source_path), _get_full_path(target_path))


def get(path: str) -> Content | None:
    """
    The stored file, or None. It is not read: the result points at the file
    (see lithica.func.content) and compares equal to the bytes in it.
    """
    full_path = _get_full_path(path)
    if not os.path.exists(full_path):
        return None
    return Content(full_path)


def save(path: str, content: ContentLike) -> None:
    full_path = _get_full_path(path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    content_module.save(content, full_path)
