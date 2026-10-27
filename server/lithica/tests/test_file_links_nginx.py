"""
The signed file links the server makes, checked by the nginx of both client
images: their own configuration files, in the nginx images they are built
on, with Docker. Skipped where Docker is not there (and the repository's
client files are not), unless LITHICA_REQUIRE_DOCKER is set, as in CI.
"""

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from lithica import model
from lithica.func import file_links, posts

ROOT = Path(__file__).resolve().parents[3]
SARDONYX = ROOT / "clients" / "sardonyx"
LEGACY = ROOT / "legacy" / "client"
SECRET = "test-secret-of-signed-file-links-0123456789"


def _docker_works() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


_AVAILABLE = SARDONYX.is_dir() and LEGACY.is_dir() and _docker_works()
if not _AVAILABLE and os.getenv("LITHICA_REQUIRE_DOCKER"):
    raise RuntimeError(
        "LITHICA_REQUIRE_DOCKER is set, but Docker or the clients are not"
    )
pytestmark = pytest.mark.skipif(not _AVAILABLE, reason="needs Docker and the clients")


def _image(dockerfile: Path, stage: str) -> str:
    """The nginx image a client's release stage is built on."""
    for line in dockerfile.read_text().splitlines():
        words = line.split()
        if words[:1] == ["FROM"] and words[-1] == stage and "nginx" in words[1]:
            return words[1]
    raise AssertionError("no nginx image in %s" % dockerfile)


def _run(args: list[str]) -> str:
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout.strip()


def _start(args: list[str], copies: dict[Path, str] | None = None) -> Iterator[str]:
    """
    A container of these arguments, with these files copied in first (as an
    image's build does: its start script may edit them in place), started.
    """
    container = _run(["docker", "create", "-p", "127.0.0.1::80", *args])
    try:
        for source, target in (copies or {}).items():
            _run(["docker", "cp", str(source), "%s:%s" % (container, target)])
        _run(["docker", "start", container])
        port = (
            _run(["docker", "port", container, "80/tcp"])
            .splitlines()[0]
            .rsplit(":")[-1]
        )
        base = "http://127.0.0.1:%s" % port
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError(_run(["docker", "logs", container]))
        yield base
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


@pytest.fixture
def data(tmp_path, config_injector) -> Path:
    config_injector({"data_url": "data/", "secret": "test"})
    root = tmp_path / "data"
    for folder in ("posts", "generated-thumbnails", "avatars"):
        (root / folder).mkdir(parents=True)
    post = _post()
    (root / posts.get_post_content_path(post)).write_text("the file")
    (root / posts.get_post_thumbnail_path(post)).write_text("the thumbnail")
    (root / "avatars" / "someone.png").write_text("an avatar")
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    return root


def _post() -> model.Post:
    post = model.Post()
    post.post_id = 5
    post.mime_type = "image/png"
    return post


def _sardonyx(data: Path, tmp_path: Path, secret: str) -> Iterator[str]:
    image = _image(SARDONYX / "Dockerfile", "release")
    yield from _start(
        [
            "-v", "%s:/data:ro" % data,
            "-v", "%s:/etc/nginx/templates/default.conf.template:ro"
            % (SARDONYX / "nginx.conf.template"),
            "-v", "%s:/docker-entrypoint.d/15-file-link-secret.sh:ro"
            % (SARDONYX / "docker-entrypoint.d" / "15-file-link-secret.sh"),
            "-e", "BACKEND_HOST=127.0.0.1",
            "-e", "RESOLVER=127.0.0.11",
            "-e", "FILE_LINK_SECRET=%s" % secret,
            image,
        ]
    )  # fmt: skip


def _legacy(data: Path, tmp_path: Path, secret: str) -> Iterator[str]:
    image = _image(LEGACY / "Dockerfile", "release")
    yield from _start(
        [
            "-v", "%s:/data:ro" % data,
            "-e", "BACKEND_HOST=127.0.0.1",
            "-e", "FILE_LINK_SECRET=%s" % secret,
            image, "sh", "/docker-start.sh",
        ],
        {
            LEGACY / "nginx.conf.docker": "/etc/nginx/nginx.conf",
            LEGACY / "docker-start.sh": "/docker-start.sh",
        },
    )  # fmt: skip


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as ex:
        return ex.code


def _read(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode()


IMAGES = {"sardonyx": _sardonyx, "legacy": _legacy}


@pytest.mark.parametrize("image", IMAGES)
def test_a_signed_link_of_the_server_is_served_and_nothing_else(
    image, data, tmp_path, config_injector
):
    for base in IMAGES[image](data, tmp_path, SECRET):
        config_injector(
            {"data_url": base + "/data/", "secret": "test", "file_link_secret": SECRET}
        )
        post = _post()
        for url, text, path in [
            (
                posts.get_post_content_url(post),
                "the file",
                posts.get_post_content_path(post),
            ),
            (
                posts.get_post_thumbnail_url(post),
                "the thumbnail",
                posts.get_post_thumbnail_path(post),
            ),
        ]:
            # the address as the server gives it out
            assert _read(url) == text
            unsigned = "%s/data/%s" % (base, path)
            assert _status(unsigned) == 403
            # the signature of another file, another expiry, one that is over
            expires = file_links.expiry()
            other = file_links.signature("/posts/6_other.png", expires, SECRET)
            assert _status("%s?e=%d&s=%s" % (unsigned, expires, other)) == 403
            right = file_links.signature("/" + path, expires, SECRET)
            assert _status("%s?e=%d&s=%s" % (unsigned, expires + 1, right)) == 403
            past = int(time.time()) - 60
            old = file_links.signature("/" + path, past, SECRET)
            assert _status("%s?e=%d&s=%s" % (unsigned, past, old)) == 403
            # signed with another secret
            wrong = file_links.signature("/" + path, expires, "x" * 40)
            assert _status("%s?e=%d&s=%s" % (unsigned, expires, wrong)) == 403
        assert _read(base + "/data/avatars/someone.png") == "an avatar"


@pytest.mark.parametrize("image", IMAGES)
def test_without_a_secret_files_are_served_as_before(
    image, data, tmp_path, config_injector
):
    for base in IMAGES[image](data, tmp_path, ""):
        config_injector({"data_url": base + "/data/", "secret": "test"})
        url = posts.get_post_content_url(_post())
        assert "?" not in url
        assert _read(url) == "the file"
        assert _read(posts.get_post_thumbnail_url(_post())) == "the thumbnail"
