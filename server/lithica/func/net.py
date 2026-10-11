import http.client
import ipaddress
import json
import logging
import socket
import subprocess
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


class _GuardedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _create_guarded_connection


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _create_guarded_connection


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_GuardedHTTPConnection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_GuardedHTTPSConnection, req)


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


def _build_opener() -> urllib.request.OpenerDirector:
    """
    An opener with nothing but guarded http and https. There is no file,
    ftp or data handler, and no proxy handler: through a proxy the server
    could not check which address is fetched.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.UnknownHandler(),
        _GuardedHTTPHandler(),
        _GuardedHTTPSHandler(),
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
    try:
        _download_into(downloaded, request, url)
        if (
            yt_dlp_error
            and mime.get_mime_type(downloaded) == "application/octet-stream"
        ):
            raise yt_dlp_error
    except BaseException:
        downloaded.delete()
        raise
    return downloaded


def _download_into(target: Content, request: urllib.request.Request, url: str) -> None:
    length_tally = 0
    try:
        with (
            _build_opener().open(request, timeout=DOWNLOAD_TIMEOUT) as handle,
            target.open_for_writing() as output,
        ):
            while chunk := handle.read(_dl_chunk_size):
                length_tally += len(chunk)
                if length_tally > config.config["max_dl_filesize"]:
                    raise DownloadTooLargeError(
                        "Download target exceeds maximum. (%d)"
                        % (config.config["max_dl_filesize"]),
                        extra_fields={"URL": url},
                    )
                output.write(chunk)
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
        raise _generic_download_error(url, ex) from None


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
