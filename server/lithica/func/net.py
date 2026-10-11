import http.client
import ipaddress
import json
import logging
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from threading import Thread
from typing import Any

from lithica import config, errors
from lithica.func import mime
from lithica.func.content import Content

logger = logging.getLogger(__name__)
_dl_chunk_size = 2**15
# seconds yt-dlp may take to resolve a URL before the request fails
YT_DLP_TIMEOUT = 60
# seconds a download may take to connect, and to deliver each chunk
DOWNLOAD_TIMEOUT = 30
# seconds a download may take in all, redirects included. The limit above
# is per step, and a server that sends a byte now and then never exceeds it.
DOWNLOAD_TOTAL_TIMEOUT = 300
# redirects followed for one download
MAX_REDIRECTS = 5
ALLOWED_SCHEMES = ("http", "https")
GENERIC_DOWNLOAD_ERROR = "Could not download the file."


class DownloadError(errors.ProcessingError):
    pass


class DownloadTooLargeError(DownloadError):
    pass


class InvalidDownloadUrlError(errors.ValidationError):
    pass


class _RefusedDownloadError(OSError):
    """The server must not fetch this: wrong address, scheme or hop count."""


class _DownloadTimedOutError(OSError):
    """The download as a whole took longer than DOWNLOAD_TOTAL_TIMEOUT."""


class _Deadline:
    """
    The moment by which one download has to be finished, redirects and all.

    Two things enforce it. Every step that is about to start (a connection,
    a read) is refused once the time is up and is given no more time than
    is left. And a step that is already waiting, for a slow header or the
    next trickle of bytes, is cut short: when the time is up a timer shuts
    the download's connections down, which ends the wait.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._ends = time.monotonic() + seconds
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self.expired = False
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def is_over(self) -> bool:
        return self.expired or time.monotonic() >= self._ends

    def check(self) -> None:
        if self.is_over():
            raise _DownloadTimedOutError(
                "the download took longer than %g seconds in all" % self.seconds
            )

    def step_timeout(self) -> float:
        """How long the next step may take: the usual limit, or what is left."""
        self.check()
        return max(min(DOWNLOAD_TIMEOUT, self._ends - time.monotonic()), 0.001)

    def track(self, connection: socket.socket) -> None:
        """Remember a connection of this download, to cut it when time is up."""
        with self._lock:
            if not self.expired:
                self._sockets.append(connection)
                return
        connection.close()
        self.check()

    def _expire(self) -> None:
        with self._lock:
            self.expired = True
            connections, self._sockets = self._sockets, []
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                # closed in the meantime
                pass

    def finish(self) -> None:
        """The download is over, one way or another: stop the timer."""
        self._timer.cancel()
        with self._lock:
            self._sockets = []


def _verify_url_scheme(url: str) -> urllib.parse.SplitResult:
    """Accept http and https URLs with a host; everything else is refused."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    if parts is None or parts.scheme.lower() not in ALLOWED_SCHEMES or not host:
        raise InvalidDownloadUrlError(
            "Only http and https URLs can be downloaded.", extra_fields={"URL": url}
        )
    return parts


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # is_global is false for loopback, private, link-local (which includes
    # the cloud metadata address 169.254.169.254), shared, reserved and
    # unspecified ranges; multicast is named because parts of it are global.
    return ip.is_global and not ip.is_multicast


def _resolve_allowed_addresses(host: str, port: int) -> list[tuple[Any, ...]]:
    """
    Resolve the host and return the socket addresses to connect to. Unless
    allow_private_downloads is set, every address must be public: one
    private address among several is enough to refuse the host.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as ex:
        raise OSError("cannot resolve %r: %s" % (host, ex)) from ex
    addresses = [info[4] for info in infos]
    if not addresses:
        raise OSError("%r resolves to nothing" % host)
    if not config.config.get("allow_private_downloads", False):
        for address in addresses:
            if not _is_public_address(str(address[0])):
                raise _RefusedDownloadError(
                    "%r resolves to the non-public address %s" % (host, address[0])
                )
    return addresses


def _create_guarded_connection(
    address: tuple[str, int],
    timeout: Any = DOWNLOAD_TIMEOUT,
    source_address: Any = None,
    **_kwargs: Any,
) -> socket.socket:
    """
    Stand-in for socket.create_connection in the download connections. It
    connects to the very address that was checked, so a host name cannot
    pass the check with one address and be fetched from another.
    """
    host, port = address
    last_error: OSError | None = None
    for checked_address in _resolve_allowed_addresses(host, port):
        try:
            return socket.create_connection(
                checked_address[:2], timeout, source_address
            )
        except OSError as ex:
            last_error = ex
    assert last_error is not None
    raise last_error


class _GuardedConnection(http.client.HTTPConnection):
    """
    A connection that is made to a checked address (see
    _create_guarded_connection) and, when it belongs to a download with a
    deadline, within the time that is left.
    """

    _deadline: _Deadline | None = None

    def _guard(self, deadline: _Deadline | None) -> None:
        self._deadline = deadline
        self._create_connection = self._create_guarded_connection

    def _create_guarded_connection(
        self,
        address: tuple[str, int],
        timeout: Any = DOWNLOAD_TIMEOUT,
        source_address: Any = None,
        **_kwargs: Any,
    ) -> socket.socket:
        if self._deadline is not None:
            timeout = self._deadline.step_timeout()
        return _create_guarded_connection(address, timeout, source_address)

    def connect(self) -> None:
        super().connect()
        # after connect() the socket is the final one: for https, the
        # encrypted one
        if self._deadline is not None:
            self._deadline.track(self.sock)


class _GuardedHTTPConnection(_GuardedConnection):
    def __init__(
        self, *args: Any, deadline: _Deadline | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._guard(deadline)


class _GuardedHTTPSConnection(_GuardedConnection, http.client.HTTPSConnection):
    def __init__(
        self, *args: Any, deadline: _Deadline | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._guard(deadline)


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, deadline: _Deadline | None = None) -> None:
        super().__init__()
        self._deadline = deadline

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        def connection(host: str, **kwargs: Any) -> _GuardedHTTPConnection:
            return _GuardedHTTPConnection(host, deadline=self._deadline, **kwargs)

        return self.do_open(connection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, deadline: _Deadline | None = None) -> None:
        super().__init__()
        self._deadline = deadline

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        def connection(host: str, **kwargs: Any) -> _GuardedHTTPSConnection:
            return _GuardedHTTPSConnection(host, deadline=self._deadline, **kwargs)

        return self.do_open(connection, req)


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        # urllib only limits how many different URLs are visited and how
        # often each; count every hop instead
        visited: dict[str, int] = getattr(req, "redirect_dict", {})
        if sum(visited.values()) >= MAX_REDIRECTS:
            raise _RefusedDownloadError("more than %d redirects" % MAX_REDIRECTS)
        # the address of every hop is checked when its connection is made;
        # the scheme has to be checked here
        try:
            _verify_url_scheme(newurl)
        except InvalidDownloadUrlError as ex:
            raise _RefusedDownloadError(
                "redirect to a URL that is not http or https"
            ) from ex
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener(
    deadline: _Deadline | None = None,
) -> urllib.request.OpenerDirector:
    """
    An opener with nothing but guarded http and https. There is no file,
    ftp or data handler, and no proxy handler: through a proxy the server
    could not check which address is fetched.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.UnknownHandler(),
        _GuardedHTTPHandler(deadline),
        _GuardedHTTPSHandler(deadline),
        urllib.request.HTTPDefaultErrorHandler(),
        _GuardedRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _generic_download_error(url: str, reason: object) -> DownloadError:
    # One message for a refused address, a failed connection and a timeout:
    # telling them apart would let the client map the server's network.
    # The reason goes to the log only.
    host = urllib.parse.urlsplit(url).hostname
    logger.warning("Download from host %r failed: %s", host, reason)
    return DownloadError(GENERIC_DOWNLOAD_ERROR, extra_fields={"URL": url})


def _verify_url(url: str) -> None:
    """Scheme and address check of a URL before anything is sent to it."""
    parts = _verify_url_scheme(url)
    assert parts.hostname
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        _resolve_allowed_addresses(parts.hostname, port)
    except (OSError, ValueError) as ex:
        raise _generic_download_error(url, ex) from None


def download(url: str, use_video_downloader: bool = False) -> Content:
    """
    Fetch the URL into a temporary file. The caller owns the result and
    deletes it when done (see lithica.func.content); nothing of the
    download is kept in memory.
    """
    assert url
    _verify_url_scheme(url)
    yt_dlp_error = None
    if use_video_downloader:
        # yt-dlp fetches the URL itself, so it is checked before yt-dlp
        # sees it. This cannot bind yt-dlp to the checked address the way
        # the download below is bound.
        _verify_url(url)
        try:
            url = _get_yt_dlp_content_url(url) or url
        except errors.ThirdPartyError as ex:
            yt_dlp_error = ex
        _verify_url_scheme(url)

    request = urllib.request.Request(url)
    if config.config["user_agent"]:
        request.add_header("User-Agent", config.config["user_agent"])
    request.add_header("Referer", url)

    downloaded = Content.create_temporary()
    deadline = _Deadline(DOWNLOAD_TOTAL_TIMEOUT)
    try:
        _download_into(downloaded, request, url, deadline)
        if (
            yt_dlp_error
            and mime.get_mime_type(downloaded) == "application/octet-stream"
        ):
            raise yt_dlp_error
    except BaseException:
        downloaded.delete()
        raise
    finally:
        deadline.finish()
    return downloaded


def _download_into(
    target: Content, request: urllib.request.Request, url: str, deadline: _Deadline
) -> None:
    length_tally = 0
    try:
        with (
            _build_opener(deadline).open(request, timeout=DOWNLOAD_TIMEOUT) as handle,
            target.open_for_writing() as output,
        ):
            while True:
                deadline.check()
                # read1 returns what has arrived instead of waiting for a
                # full chunk, so a slow server cannot hold one read for long
                chunk = handle.read1(_dl_chunk_size)
                if not chunk:
                    break
                length_tally += len(chunk)
                if length_tally > config.config["max_dl_filesize"]:
                    raise DownloadTooLargeError(
                        "Download target exceeds maximum. (%d)"
                        % (config.config["max_dl_filesize"]),
                        extra_fields={"URL": url},
                    )
                output.write(chunk)
            # a connection cut at the deadline looks like the end of the file
            deadline.check()
    except urllib.error.HTTPError as ex:
        if 300 <= ex.code < 400:
            # a redirect that was not followed: too many hops, or a loop
            raise _generic_download_error(url, ex) from None
        raise DownloadError(
            "Download target returned HTTP %d. (%s)" % (ex.code, ex.reason),
            extra_fields={"URL": url},
        ) from ex
    except (OSError, http.client.HTTPException, ValueError) as ex:
        # URLError and timeouts are OSErrors
        reason: object = ex
        if deadline.is_over() and not isinstance(ex, _DownloadTimedOutError):
            # whatever the cut connection, or a step that was given only
            # the time that was left, made of it: this is the cause
            reason = "the download took longer than %g seconds in all (%s)" % (
                deadline.seconds,
                ex,
            )
        raise _generic_download_error(url, reason) from None


def _get_yt_dlp_content_url(url: str) -> str:
    cmd = ["yt-dlp", "--format", "best", "--no-playlist"]
    if config.config["user_agent"]:
        cmd.extend(["--user-agent", config.config["user_agent"]])
    # "--" ends the options: the URL comes from the user, and without it a
    # value starting with "-" would be read by yt-dlp as an option.
    cmd.extend(["--get-url", "--", url])
    try:
        return (
            subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=True,
                stdin=subprocess.DEVNULL,
                timeout=YT_DLP_TIMEOUT,
            )
            .stdout.split("\n")[0]
            .strip()
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise errors.ThirdPartyError(
            "Could not extract content location from URL.",
            extra_fields={"URL": url},
        ) from None


def post_to_webhooks(payload: dict[str, Any]) -> list[Thread]:
    threads = [
        Thread(target=_post_to_webhook, args=(webhook, payload), daemon=False)
        for webhook in (config.config["webhooks"] or [])
    ]
    for thread in threads:
        thread.start()
    return threads


def _post_to_webhook(webhook: str, payload: dict[str, Any]) -> int:
    req = urllib.request.Request(webhook)
    req.data = json.dumps(
        payload,
        default=lambda x: x.isoformat("T") + "Z",
    ).encode("utf-8")
    req.add_header("Content-Type", "application/json")
    try:
        res = urllib.request.urlopen(req)
        if not 200 <= res.status <= 299:
            logger.warning(f"Webhook {webhook} returned {res.status} {res.reason}")
        return res.status
    except urllib.error.URLError as ex:
        logger.warning(f"Unable to call webhook {webhook}: {ex}")
        return 400
