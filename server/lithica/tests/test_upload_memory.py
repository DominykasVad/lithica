"""
PLAN.md 2.3: uploading a large video does not grow the server's memory by
the size of the file. Measured on a real server process, see upload_server.
"""

import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

MEGABYTE = 1024 * 1024
BOUNDARY = "----lithicamemorytest"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Server:
    def __init__(self, port: int) -> None:
        self.port = port

    def _connection(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)

    def peak_rss(self) -> int:
        connection = self._connection()
        connection.request("GET", "/_peak_rss")
        peak = int(connection.getresponse().read())
        connection.close()
        return peak

    def upload(self, size: int) -> tuple[int, dict, str]:
        """
        Upload `size` bytes as a temporary file, a megabyte at a time, so
        that this process never holds the file either. Returns the status,
        the response and the SHA-1 of what was sent.
        """
        head = (
            '--%s\r\nContent-Disposition: form-data; name="content"; '
            'filename="large.mp4"\r\nContent-Type: video/mp4\r\n\r\n' % BOUNDARY
        ).encode()
        tail = ("\r\n--%s--\r\n" % BOUNDARY).encode()
        digest = hashlib.sha1()

        def body() -> Iterator[bytes]:
            yield head
            # not all the same byte, so a lost or repeated block changes the hash
            for number in range(size // MEGABYTE):
                block = bytes([number % 251]) * MEGABYTE
                digest.update(block)
                yield block
            yield tail

        connection = self._connection()
        connection.request(
            "POST",
            "/uploads",
            body=body(),
            headers={
                "Accept": "application/json",
                "Content-Type": "multipart/form-data; boundary=%s" % BOUNDARY,
                "Content-Length": str(len(head) + size + len(tail)),
            },
        )
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result, digest.hexdigest()


def _wait_until_empty(folder: str) -> list[str]:
    """
    What is in the folder once the server has cleaned up, at the latest
    after ten seconds. The server removes the folder of a request after it
    has sent the response, so a client that has just read the response can
    be a moment ahead of it.
    """
    deadline = time.monotonic() + 10
    while os.listdir(folder) and time.monotonic() < deadline:
        time.sleep(0.05)
    return os.listdir(folder)


@pytest.fixture
def server(tmpdir):
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "lithica.tests.upload_server", str(port), str(tmpdir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    server = _Server(port)
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                server.peak_rss()
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    output = process.stdout.read().decode() if process.stdout else ""
                    pytest.fail("the upload server did not start:\n" + output)
                time.sleep(0.1)
        yield server
    finally:
        process.terminate()
        process.wait(timeout=30)


def test_large_upload_does_not_grow_the_server_by_its_size(server, tmpdir):
    size = 256 * MEGABYTE

    # a first upload, large enough to go to disk, so that everything the
    # upload path loads and allocates once is in the baseline
    status, _result, _sha1 = server.upload(4 * MEGABYTE)
    assert status == 200
    before = server.peak_rss()

    status, result, sha1 = server.upload(size)
    assert status == 200, result
    after = server.peak_rss()

    # the file arrived whole
    assert result["token"] == sha1
    stored = os.path.join(str(tmpdir), "temporary-uploads", sha1 + ".dat")
    assert os.path.getsize(stored) == size
    # it was written once, into the data directory, and renamed into place:
    # the folder for temporary files is empty again
    temporary = os.path.join(str(tmpdir), "temporary-uploads", ".tmp")
    assert _wait_until_empty(temporary) == []

    # and the server needed a small fraction of it in memory
    growth = after - before
    assert growth < size // 8, "the server grew by %.1f MB for a %d MB upload" % (
        growth / MEGABYTE,
        size // MEGABYTE,
    )


def test_request_larger_than_the_limit_is_refused_by_a_real_server(server, tmpdir):
    # the limit of the test server is 1 GiB; declare more than that
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
    connection.putrequest("POST", "/uploads")
    connection.putheader("Accept", "application/json")
    connection.putheader("Content-Type", "multipart/form-data; boundary=x")
    connection.putheader("Content-Length", str(1024 * MEGABYTE + 1))
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 413
    assert json.loads(response.read())["name"] == "RequestTooLargeError"
    connection.close()
    # nothing was stored, and nothing is left in the folder for temporary files
    uploads = os.path.join(str(tmpdir), "temporary-uploads")
    assert os.listdir(uploads) == [".tmp"]
    assert _wait_until_empty(os.path.join(uploads, ".tmp")) == []
