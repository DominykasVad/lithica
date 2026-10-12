"""
Tests of what net.download agrees to fetch. Nothing here leaves the machine:
name resolution is replaced, and "public" hosts are served by an HTTP server
on the loopback interface.
"""

import http.server
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from unittest.mock import patch

import pytest

from lithica import errors, registry
from lithica.func import net

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "151.101.1.69"


Reply = tuple[int, dict[str, str], bytes]


class _WebServer(http.server.ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes: dict[str, Reply | Callable[[], Reply]] = {}
        self.raw_routes: dict[str, Callable[[_Handler], None]] = {}
        self.requests: list[tuple[str | None, str]] = []
        self.port: int = self.server_address[1]


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        server = self.server
        assert isinstance(server, _WebServer)
        server.requests.append((self.headers.get("Host"), self.path))
        if self.path in server.raw_routes:
            # the route writes its own response, at its own pace
            server.raw_routes[self.path](self)
            return
        action = server.routes.get(self.path, (404, {}, b"not found"))
        status, headers, body = action() if callable(action) else action
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def web():
    """A local HTTP server; set web.routes[path] = (status, headers, body)."""
    server = _WebServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def network(web):
    """
    Replace DNS and TCP connects. network.hosts maps a host name to the
    addresses it "resolves" to. A connection to a public address lands on
    the local web server; network.connections records where the code
    tried to connect.
    """

    class Network:
        hosts: dict[str, list[str]] = {}
        connections: list[str] = []

    state = Network()
    state.hosts = {}
    state.connections = []
    real_getaddrinfo = socket.getaddrinfo
    real_create_connection = socket.create_connection

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in state.hosts:
            return [
                (
                    socket.AF_INET6 if ":" in address else socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (address, port),
                )
                for address in state.hosts[host]
            ]
        # IP literals need no name server
        return real_getaddrinfo(
            host, port, *args, **{**kwargs, "flags": socket.AI_NUMERICHOST}
        )

    def fake_create_connection(address, timeout=None, source_address=None, **kwargs):
        state.connections.append(address[0])
        return real_create_connection(("127.0.0.1", web.port), timeout)

    with (
        patch("lithica.func.net.socket.getaddrinfo", side_effect=fake_getaddrinfo),
        patch(
            "lithica.func.net.socket.create_connection",
            side_effect=fake_create_connection,
        ),
    ):
        yield state


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "user_agent": None,
            "max_dl_filesize": 1.0e6,
            "allow_private_downloads": False,
        }
    )


def _assert_generic_error(excinfo):
    assert type(excinfo.value) is net.DownloadError
    assert str(excinfo.value) == net.GENERIC_DOWNLOAD_ERROR


def test_download_from_public_host(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    web.routes["/file.png"] = (200, {}, b"content")
    assert net.download("http://public.example/file.png") == b"content"
    assert network.connections == [PUBLIC_IP]
    assert web.requests == [("public.example", "/file.png")]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://localhost/etc/passwd",
        "ftp://public.example/file.png",
        "gopher://public.example/",
        "data:text/plain;base64,aGVsbG8=",
        "javascript:alert(1)",
        "//public.example/file.png",
        "public.example/file.png",
        "/etc/passwd",
        "http:///file.png",
        "http://",
        "HTTPX://public.example/",
        "http://[::1",
    ],
)
def test_only_http_and_https(network, url):
    network.hosts["public.example"] = [PUBLIC_IP]
    with pytest.raises(net.InvalidDownloadUrlError) as excinfo:
        net.download(url)
    assert isinstance(excinfo.value, errors.ValidationError)
    assert network.connections == []


def test_scheme_is_case_insensitive(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    web.routes["/file.png"] = (200, {}, b"content")
    assert net.download("HTTP://public.example/file.png") == b"content"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://127.8.9.10/",
        "http://[::1]/",
        "http://[::1]:6666/info",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fe80::1]/",
        "http://10.0.0.1/",
        "http://172.16.5.4/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::]/",
        "http://224.0.0.1/",
        "http://239.255.255.250/",
        "http://[ff02::1]/",
        "http://240.0.0.1/",
        "http://255.255.255.255/",
        "http://[fc00::1]/",
        "http://[fd12:3456::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
        "https://127.0.0.1/",
        "https://[::1]/",
    ],
)
def test_non_public_addresses_are_refused(network, url):
    with pytest.raises(net.DownloadError) as excinfo:
        net.download(url)
    _assert_generic_error(excinfo)
    assert network.connections == []


@pytest.mark.parametrize(
    "addresses",
    [
        ["10.1.2.3"],
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["fd00::5"],
        # one private address among public ones is enough
        [PUBLIC_IP, "192.168.0.10"],
        ["192.168.0.10", PUBLIC_IP],
        [PUBLIC_IP, "::1"],
    ],
)
def test_host_name_resolving_to_non_public_address_is_refused(network, addresses):
    network.hosts["sneaky.example"] = addresses
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://sneaky.example/file.png")
    _assert_generic_error(excinfo)
    assert network.connections == []


def test_connection_goes_to_the_address_that_was_checked(web, network):
    # a name server that answers differently on every question
    answers = iter([[PUBLIC_IP], ["127.0.0.1"], ["127.0.0.1"]])
    network.hosts["rebind.example"] = [PUBLIC_IP]
    real_fake = net.socket.getaddrinfo.side_effect

    def changing_getaddrinfo(host, port, *args, **kwargs):
        network.hosts["rebind.example"] = next(answers)
        return real_fake(host, port, *args, **kwargs)

    web.routes["/file.png"] = (200, {}, b"content")
    with patch.object(net.socket.getaddrinfo, "side_effect", changing_getaddrinfo):
        assert net.download("http://rebind.example/file.png") == b"content"
    # resolved once, and connected to that answer
    assert network.connections == [PUBLIC_IP]


def test_redirect_to_public_host_is_followed(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    network.hosts["cdn.example"] = [OTHER_PUBLIC_IP]
    web.routes["/start"] = (302, {"Location": "http://cdn.example/file.png"}, b"")
    web.routes["/file.png"] = (200, {}, b"content")
    assert net.download("http://public.example/start") == b"content"
    assert network.connections == [PUBLIC_IP, OTHER_PUBLIC_IP]


@pytest.mark.parametrize(
    "location",
    [
        "http://internal.example/secret",
        "http://127.0.0.1/secret",
        "http://[::1]/secret",
        "http://169.254.169.254/latest/meta-data/",
        "https://internal.example/secret",
    ],
)
def test_redirect_to_non_public_address_is_refused(web, network, location):
    network.hosts["public.example"] = [PUBLIC_IP]
    network.hosts["internal.example"] = ["10.0.0.5"]
    web.routes["/start"] = (302, {"Location": location}, b"")
    web.routes["/secret"] = (200, {}, b"secret")
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://public.example/start")
    _assert_generic_error(excinfo)
    # only the first, public, hop was ever connected to
    assert network.connections == [PUBLIC_IP]
    assert web.requests == [("public.example", "/start")]


def test_private_address_is_refused_at_a_later_hop(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    network.hosts["cdn.example"] = [OTHER_PUBLIC_IP]
    network.hosts["internal.example"] = ["192.168.7.7"]
    web.routes["/a"] = (302, {"Location": "http://cdn.example/b"}, b"")
    web.routes["/b"] = (301, {"Location": "http://cdn.example/c"}, b"")
    web.routes["/c"] = (307, {"Location": "http://internal.example/secret"}, b"")
    web.routes["/secret"] = (200, {}, b"secret")
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://public.example/a")
    _assert_generic_error(excinfo)
    assert network.connections == [PUBLIC_IP, OTHER_PUBLIC_IP, OTHER_PUBLIC_IP]


@pytest.mark.parametrize(
    "location", ["file:///etc/passwd", "ftp://public.example/x", "gopher://x/"]
)
def test_redirect_to_another_scheme_is_refused(web, network, location):
    network.hosts["public.example"] = [PUBLIC_IP]
    web.routes["/start"] = (302, {"Location": location}, b"")
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://public.example/start")
    _assert_generic_error(excinfo)
    assert network.connections == [PUBLIC_IP]


def test_redirects_are_followed_up_to_the_limit(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    for hop in range(net.MAX_REDIRECTS):
        web.routes["/hop%d" % hop] = (
            302,
            {"Location": "http://public.example/hop%d" % (hop + 1)},
            b"",
        )
    web.routes["/hop%d" % net.MAX_REDIRECTS] = (200, {}, b"content")
    assert net.download("http://public.example/hop0") == b"content"
    assert len(web.requests) == net.MAX_REDIRECTS + 1


def test_too_many_redirects(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    for hop in range(net.MAX_REDIRECTS + 1):
        web.routes["/hop%d" % hop] = (
            302,
            {"Location": "http://public.example/hop%d" % (hop + 1)},
            b"",
        )
    web.routes["/hop%d" % (net.MAX_REDIRECTS + 1)] = (200, {}, b"content")
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://public.example/hop0")
    _assert_generic_error(excinfo)
    assert len(web.requests) == net.MAX_REDIRECTS + 1


def test_redirect_loop(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    web.routes["/a"] = (302, {"Location": "http://public.example/b"}, b"")
    web.routes["/b"] = (302, {"Location": "http://public.example/a"}, b"")
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://public.example/a")
    _assert_generic_error(excinfo)
    assert len(web.requests) <= net.MAX_REDIRECTS + 1


def test_connect_timeout(network):
    network.hosts["public.example"] = [PUBLIC_IP]
    with patch(
        "lithica.func.net.socket.create_connection", side_effect=TimeoutError()
    ) as create_connection:
        with pytest.raises(net.DownloadError) as excinfo:
            net.download("http://public.example/file.png")
    _assert_generic_error(excinfo)
    address, timeout = create_connection.call_args[0][:2]
    assert address == (PUBLIC_IP, 80)
    assert timeout == net.DOWNLOAD_TIMEOUT == 30


def test_read_timeout(web, network, monkeypatch):
    monkeypatch.setattr(net, "DOWNLOAD_TIMEOUT", 0.3)
    network.hosts["public.example"] = [PUBLIC_IP]

    def slow():
        time.sleep(2)
        return (200, {}, b"content")

    web.routes["/slow"] = slow
    started = time.monotonic()
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://public.example/slow")
    _assert_generic_error(excinfo)
    assert time.monotonic() - started < 1.5


def test_connection_refused(network):
    network.hosts["public.example"] = [PUBLIC_IP]
    with patch(
        "lithica.func.net.socket.create_connection",
        side_effect=ConnectionRefusedError(),
    ):
        with pytest.raises(net.DownloadError) as excinfo:
            net.download("http://public.example/file.png")
    _assert_generic_error(excinfo)


def test_unresolvable_host(network):
    with patch(
        "lithica.func.net.socket.getaddrinfo", side_effect=socket.gaierror(8, "x")
    ):
        with pytest.raises(net.DownloadError) as excinfo:
            net.download("http://nowhere.example/file.png")
    _assert_generic_error(excinfo)


def test_failures_look_the_same_to_the_client(web, network, caplog):
    network.hosts["public.example"] = [PUBLIC_IP]
    network.hosts["internal.example"] = ["10.0.0.5"]

    def failure(url, **patches):
        with pytest.raises(net.DownloadError) as excinfo:
            if patches:
                with patch("lithica.func.net.socket.create_connection", **patches):
                    net.download(url)
            else:
                net.download(url)
        return (type(excinfo.value), str(excinfo.value))

    with caplog.at_level("WARNING", logger="lithica.func.net"):
        outcomes = {
            failure("http://internal.example/x"),
            failure("http://127.0.0.1/x"),
            failure("http://public.example/x", side_effect=TimeoutError()),
            failure("http://public.example/x", side_effect=ConnectionRefusedError()),
        }
    assert outcomes == {(net.DownloadError, net.GENERIC_DOWNLOAD_ERROR)}
    # the details are in the server log, not in the answer
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "10.0.0.5" in logged
    assert "non-public address" in logged
    assert "10.0.0.5" not in net.GENERIC_DOWNLOAD_ERROR


def test_http_error_of_a_public_host_is_reported(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://public.example/missing")
    assert "HTTP 404" in str(excinfo.value)


def test_download_too_large(web, network, config_injector):
    config_injector(
        {"user_agent": None, "max_dl_filesize": 10, "allow_private_downloads": False}
    )
    network.hosts["public.example"] = [PUBLIC_IP]
    web.routes["/big"] = (200, {}, b"x" * 100)
    with pytest.raises(net.DownloadTooLargeError):
        net.download("http://public.example/big")


def test_environment_proxy_is_not_used(web, network, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.example:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    network.hosts["public.example"] = [PUBLIC_IP]
    network.hosts["proxy.example"] = [OTHER_PUBLIC_IP]
    web.routes["/file.png"] = (200, {}, b"content")
    assert net.download("http://public.example/file.png") == b"content"
    assert network.connections == [PUBLIC_IP]


# allow_private_downloads


@pytest.fixture
def allow_private(config_injector):
    config_injector(
        {"user_agent": None, "max_dl_filesize": 1.0e6, "allow_private_downloads": True}
    )


def test_private_downloads_can_be_allowed(web, allow_private):
    # no patching at all: this is a real connection to the loopback server
    web.routes["/file.png"] = (200, {}, b"content")
    url = "http://127.0.0.1:%d/file.png" % web.port
    assert net.download(url) == b"content"


def test_private_redirect_can_be_allowed(web, allow_private):
    web.routes["/start"] = (
        302,
        {"Location": "http://127.0.0.1:%d/file.png" % web.port},
        b"",
    )
    web.routes["/file.png"] = (200, {}, b"content")
    assert net.download("http://127.0.0.1:%d/start" % web.port) == b"content"


def test_switch_is_off_by_default(web, config_injector):
    config_injector({"user_agent": None, "max_dl_filesize": 1.0e6})
    web.routes["/file.png"] = (200, {}, b"content")
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://127.0.0.1:%d/file.png" % web.port)
    _assert_generic_error(excinfo)
    assert web.requests == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://127.0.0.1/x"])
def test_scheme_check_stays_on_with_private_downloads(allow_private, url):
    with pytest.raises(net.InvalidDownloadUrlError):
        net.download(url)


def test_redirect_scheme_check_stays_on_with_private_downloads(web, allow_private):
    web.routes["/start"] = (302, {"Location": "file:///etc/passwd"}, b"")
    with pytest.raises(net.DownloadError) as excinfo:
        net.download("http://127.0.0.1:%d/start" % web.port)
    _assert_generic_error(excinfo)


# the video downloader


def _yt_dlp_result(stdout):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)


def test_video_downloader_result_is_downloaded(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    network.hosts["cdn.example"] = [OTHER_PUBLIC_IP]
    web.routes["/video.mp4"] = (200, {}, b"video")
    with patch("subprocess.run") as run:
        run.return_value = _yt_dlp_result("http://cdn.example/video.mp4\n")
        content = net.download("http://public.example/watch", True)
    assert content == b"video"
    assert network.connections == [OTHER_PUBLIC_IP]


def test_file_nobody_knows_is_the_video_downloader_s_failure(web, network):
    network.hosts["public.example"] = [PUBLIC_IP]
    web.routes["/file"] = (200, {}, b"unknown bytes")
    with patch("subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(1, "yt-dlp")
        with pytest.raises(errors.ThirdPartyError):
            net.download("http://public.example/file", True)


def test_file_of_a_module_is_downloaded_where_the_video_downloader_fails(web, network):
    # the video downloader knows nothing of a module's files; that it found
    # no video at the address does not make the file there unknown
    registry.use(
        [
            registry.Module(
                name="probe",
                file_types=[
                    registry.FileType(
                        post_type="probefile",
                        mime_type="application/x-probe",
                        extension="probe",
                        detect=lambda head, handle: head.startswith(b"PROBE"),
                    )
                ],
            )
        ]
    )
    network.hosts["public.example"] = [PUBLIC_IP]
    web.routes["/file"] = (200, {}, b"PROBE and more")
    web.routes["/other"] = (200, {}, b"unknown bytes")
    with patch("subprocess.run") as run:
        run.side_effect = subprocess.CalledProcessError(1, "yt-dlp")
        assert net.download("http://public.example/file", True) == b"PROBE and more"
        with pytest.raises(errors.ThirdPartyError):
            net.download("http://public.example/other", True)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://public.example/x", "--exec=id"]
)
def test_video_downloader_never_sees_other_schemes(network, url):
    with patch("subprocess.run") as run:
        with pytest.raises(net.InvalidDownloadUrlError):
            net.download(url, True)
    run.assert_not_called()


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/x", "http://169.254.169.254/", "http://internal.example/x"],
)
def test_video_downloader_never_sees_non_public_hosts(network, url):
    network.hosts["internal.example"] = ["10.0.0.5"]
    with patch("subprocess.run") as run:
        with pytest.raises(net.DownloadError) as excinfo:
            net.download(url, True)
    _assert_generic_error(excinfo)
    run.assert_not_called()


@pytest.mark.parametrize(
    "returned_url", ["file:///etc/passwd", "ftp://cdn.example/video.mp4"]
)
def test_video_downloader_returning_another_scheme(network, returned_url):
    network.hosts["public.example"] = [PUBLIC_IP]
    with patch("subprocess.run") as run:
        run.return_value = _yt_dlp_result(returned_url + "\n")
        with pytest.raises(net.InvalidDownloadUrlError) as excinfo:
            net.download("http://public.example/watch", True)
    assert isinstance(excinfo.value, errors.ValidationError)
    assert network.connections == []


@pytest.mark.parametrize(
    "returned_url",
    ["http://127.0.0.1/video.mp4", "http://internal.example/video.mp4"],
)
def test_video_downloader_returning_non_public_host(network, returned_url):
    network.hosts["public.example"] = [PUBLIC_IP]
    network.hosts["internal.example"] = ["10.0.0.5"]
    with patch("subprocess.run") as run:
        run.return_value = _yt_dlp_result(returned_url + "\n")
        with pytest.raises(net.DownloadError) as excinfo:
            net.download("http://public.example/watch", True)
    _assert_generic_error(excinfo)
    assert network.connections == []


# ---------------------------------------------------------------------------
# the limit on the whole download (DOWNLOAD_TOTAL_TIMEOUT)


def test_total_timeout_is_five_minutes():
    assert net.DOWNLOAD_TOTAL_TIMEOUT == 300


@pytest.fixture
def total_timeout(monkeypatch):
    """Shrink the limit on the whole download, so that the tests are quick."""

    def set_limit(seconds: float) -> None:
        monkeypatch.setattr(net, "DOWNLOAD_TOTAL_TIMEOUT", seconds)

    return set_limit


def _trickle(pause: float, count: int, sent: list[int]) -> Callable[[_Handler], None]:
    """A response body that arrives one byte at a time, `pause` apart."""

    def respond(handler: _Handler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Length", str(count))
        handler.end_headers()
        try:
            for _ in range(count):
                handler.wfile.write(b"x")
                handler.wfile.flush()
                sent.append(1)
                time.sleep(pause)
        except OSError:
            # the downloader hung up
            pass

    return respond


def test_trickling_server_is_cut_off_after_the_total_timeout(
    web, network, total_timeout, caplog
):
    # A byte every 50 ms, for 30 s if nobody stops it. No single read waits
    # anywhere near DOWNLOAD_TIMEOUT (30 s), so only the limit on the whole
    # download can end this.
    network.hosts = {"public.example": [PUBLIC_IP]}
    sent: list[int] = []
    web.raw_routes["/trickle"] = _trickle(0.05, 600, sent)
    total_timeout(0.5)
    started = time.monotonic()
    with pytest.raises(net.DownloadError) as ex:
        net.download("http://public.example/trickle")
    elapsed = time.monotonic() - started
    _assert_generic_error(ex)
    assert 0.4 < elapsed < 3
    # the server was still sending: it was the downloader that gave up
    assert 0 < len(sent) < 100
    # the reason is in the log, not in the answer
    assert "took longer than 0.5 seconds in all" in caplog.text
    assert "took longer" not in str(ex.value)


def test_slow_headers_are_cut_off_after_the_total_timeout(
    web, network, total_timeout, caplog
):
    # the same trick before the body: a header that never finishes
    network.hosts = {"public.example": [PUBLIC_IP]}

    def slow_headers(handler: _Handler) -> None:
        try:
            handler.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
            for _ in range(600):
                handler.wfile.write(b"x")
                handler.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass

    web.raw_routes["/slow-headers"] = slow_headers
    total_timeout(0.5)
    started = time.monotonic()
    with pytest.raises(net.DownloadError) as ex:
        net.download("http://public.example/slow-headers")
    _assert_generic_error(ex)
    assert time.monotonic() - started < 3
    assert "took longer than 0.5 seconds in all" in caplog.text


def test_total_timeout_covers_the_redirects(web, network, total_timeout, caplog):
    # four hops of 0.2 s each: none is slow, together they are too slow
    network.hosts = {"public.example": [PUBLIC_IP]}

    def hop(number: int) -> Callable[[], Reply]:
        def reply() -> Reply:
            time.sleep(0.2)
            if number == 4:
                return (200, {}, b"content")
            return (302, {"Location": "/hop%d" % (number + 1)}, b"")

        return reply

    for number in range(5):
        web.routes["/hop%d" % number] = hop(number)
    total_timeout(0.5)
    with pytest.raises(net.DownloadError) as ex:
        net.download("http://public.example/hop0")
    _assert_generic_error(ex)
    assert "took longer than 0.5 seconds in all" in caplog.text
    # it stopped part of the way
    assert len(web.requests) < 5


def test_slow_download_within_the_total_timeout_succeeds(web, network, total_timeout):
    network.hosts = {"public.example": [PUBLIC_IP]}
    sent: list[int] = []
    web.raw_routes["/trickle"] = _trickle(0.02, 10, sent)
    total_timeout(5)
    assert net.download("http://public.example/trickle") == b"x" * 10


def test_no_step_is_given_more_time_than_is_left(network, total_timeout):
    # a connection attempt late in a download may only take what remains
    network.hosts = {"public.example": [PUBLIC_IP]}
    total_timeout(4)
    with patch(
        "lithica.func.net.socket.create_connection", side_effect=TimeoutError()
    ) as connect:
        with pytest.raises(net.DownloadError):
            net.download("http://public.example/file.png")
    timeout = connect.call_args[0][1]
    assert 3 < timeout <= 4


def test_deadline_refuses_a_step_after_it_has_passed():
    deadline = net._Deadline(0.05)
    try:
        assert 0 < deadline.step_timeout() <= 0.05
        time.sleep(0.15)
        assert deadline.expired
        with pytest.raises(net._DownloadTimedOutError):
            deadline.check()
        with pytest.raises(net._DownloadTimedOutError):
            deadline.step_timeout()
        # a connection made too late is closed, not used
        late = socket.socket()
        with pytest.raises(net._DownloadTimedOutError):
            deadline.track(late)
        assert late.fileno() == -1
    finally:
        deadline.finish()


def test_finished_download_leaves_no_timer_running(web, network):
    network.hosts = {"public.example": [PUBLIC_IP]}
    web.routes["/file.png"] = (200, {}, b"content")

    def timers() -> int:
        return sum(isinstance(t, threading.Timer) for t in threading.enumerate())

    before = timers()
    assert net.download("http://public.example/file.png") == b"content"
    with pytest.raises(net.DownloadError):
        net.download("http://public.example/missing")
    deadline = time.monotonic() + 2
    while timers() > before and time.monotonic() < deadline:
        time.sleep(0.01)
    assert timers() == before
