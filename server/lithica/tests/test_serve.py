import socket
import threading
from unittest.mock import patch

import pytest

from lithica import serve


def _ipv6_available() -> bool:
    try:
        with socket.socket(socket.AF_INET6) as probe:
            probe.bind(("::1", 0))
        return True
    except OSError:
        return False


needs_ipv6 = pytest.mark.skipif(not _ipv6_available(), reason="no IPv6 on this host")


def _answers(listener: socket.socket, family: int, address: str) -> bool:
    """Whether a connection to the address reaches the listening socket."""
    listener.listen()
    listener.settimeout(5)
    accepted = []

    def accept() -> None:
        try:
            connection, _peer = listener.accept()
            accepted.append(connection.recv(5))
            connection.close()
        except OSError:
            pass

    thread = threading.Thread(target=accept)
    thread.start()
    try:
        with socket.socket(family) as client:
            client.settimeout(2)
            client.connect((address, listener.getsockname()[1]))
            client.sendall(b"hello")
    except OSError:
        return False
    finally:
        thread.join(timeout=6)
    return accepted == [b"hello"]


@needs_ipv6
def test_default_host_listens_on_ipv4_and_ipv6():
    listener = serve.listening_socket("::", 0)
    try:
        assert _answers(listener, socket.AF_INET, "127.0.0.1")
        assert _answers(listener, socket.AF_INET6, "::1")
    finally:
        listener.close()


@needs_ipv6
def test_ipv4_host_listens_on_ipv4_only():
    listener = serve.listening_socket("0.0.0.0", 0)
    try:
        assert _answers(listener, socket.AF_INET, "127.0.0.1")
        port = listener.getsockname()[1]
        with socket.socket(socket.AF_INET6) as client:
            client.settimeout(2)
            with pytest.raises(OSError):
                client.connect(("::1", port))
    finally:
        listener.close()


def test_socket_is_inherited_by_worker_processes():
    listener = serve.listening_socket("127.0.0.1", 0)
    try:
        assert listener.get_inheritable()
    finally:
        listener.close()


@pytest.fixture
def started(monkeypatch):
    """Run serve.main() with everything that would serve replaced; report it."""
    for name in ["HOST", "PORT", "WORKERS"]:
        monkeypatch.delenv(name, raising=False)
    seen = {}

    def fake_socket(host, port):
        seen["address"] = (host, port)
        return "the socket"

    def run(self, sockets=None):
        seen["mode"] = "single"
        seen["sockets"] = sockets
        seen["config"] = self.config
        self.started = True

    class Supervisor:
        def __init__(self, config, target=None, sockets=None):
            seen["sockets"] = sockets
            seen["config"] = config

        def run(self):
            seen["mode"] = type(self).__name__

    with (
        patch.object(serve, "listening_socket", fake_socket),
        patch.object(serve.uvicorn.Server, "run", run),
        patch.object(serve, "ChangeReload", type("reload", (Supervisor,), {})),
        patch.object(serve, "Multiprocess", type("workers", (Supervisor,), {})),
    ):
        yield seen


def test_defaults(started):
    assert serve.main([]) == 0
    assert started["address"] == ("::", 6666)
    assert started["mode"] == "single"
    assert started["sockets"] == ["the socket"]
    assert started["config"].app == "lithica.app:app"
    assert started["config"].access_log is False


def test_settings_come_from_the_environment(started, monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "7777")
    monkeypatch.setenv("WORKERS", "3")
    assert serve.main([]) == 0
    assert started["address"] == ("0.0.0.0", 7777)
    assert started["mode"] == "workers"
    assert started["config"].workers == 3
    assert started["sockets"] == ["the socket"]


def test_empty_settings_mean_the_defaults(started, monkeypatch):
    # compose passes a variable that is listed but not set as empty
    for name in ["HOST", "PORT", "WORKERS"]:
        monkeypatch.setenv(name, "")
    assert serve.main([]) == 0
    assert started["address"] == ("::", 6666)
    assert started["mode"] == "single"


def test_reload(started):
    assert serve.main(["--reload"]) == 0
    assert started["mode"] == "reload"
    assert started["sockets"] == ["the socket"]


def test_address_that_cannot_be_bound(monkeypatch, capsys):
    monkeypatch.delenv("HOST", raising=False)

    def refuse(_host, _port):
        raise OSError("Address family not supported by protocol")

    with patch.object(serve, "listening_socket", refuse):
        assert serve.main([]) == serve.STARTUP_FAILURE
    message = capsys.readouterr().err
    assert "Cannot listen on ::" in message
    assert "HOST=0.0.0.0" in message
