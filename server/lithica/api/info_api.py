import os
import threading
from datetime import datetime, timedelta
from typing import Any

from lithica import config, registry
from lithica.api import resources
from lithica.api.dependencies import CurrentUser, max_upload_size
from lithica.api.routing import ApiRouter
from lithica.func import auth, file_types, mailer, posts, users, util, visibility

router = ApiRouter(tags=["Info"])

# How long a measured disk usage is served before it is measured again.
DISK_USAGE_TTL = timedelta(hours=1)


class _DiskUsage:
    """
    Size of the data directory, for the info endpoint.

    Walking the directory is slow on a large installation, so it runs in a
    background thread and requests are answered with the last result: None
    until the first walk has finished, then a number at most DISK_USAGE_TTL
    old (plus the length of one walk).

    The state lives in this process. Every server process measures for
    itself, so two processes can report slightly different sizes for up to
    DISK_USAGE_TTL. Nothing depends on the number being the same; it is
    display-only. The lock makes one process start one walk at a time.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: int | None = None
        self._measured_at: datetime | None = None
        self._measuring = False

    def get(self) -> int | None:
        with self._lock:
            stale = (
                self._measured_at is None
                or util.utcnow() - self._measured_at > DISK_USAGE_TTL
            )
            start = stale and not self._measuring
            if start:
                self._measuring = True
        if start:
            self._start_measuring()
        with self._lock:
            return self._value

    def _start_measuring(self) -> None:
        threading.Thread(target=self._measure, daemon=True).start()

    def _measure(self) -> None:
        try:
            total_size = 0
            for dirpath, _, filenames in os.walk(config.config["data_dir"]):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total_size += os.path.getsize(fp)
                    except FileNotFoundError:
                        pass
            with self._lock:
                self._value = total_size
                self._measured_at = util.utcnow()
        finally:
            # also after an error, or no later request could measure again
            with self._lock:
                self._measuring = False


_disk_usage = _DiskUsage()


@router.get("/info", response_model=resources.Info, summary="Get global info")
def get_info(user: CurrentUser) -> dict[str, Any]:
    """
    Retrieves simple statistics. `<featured-post>` is null if there is no
    featured post yet. `<server-time>` is pretty much the same as the `Date`
    HTTP field, only formatted in a manner consistent with other dates. Values
    in `config` key are taken directly from the server config, with the
    exception of privilege array keys being converted to lower camel case to
    match the API convention.

    `<modules>` are the names of the optional modules this server has switched
    on, in the order of its configuration; empty on a plain installation. A
    module's routes are under `modules/<name>/`.

    `<max-upload-size>` is the largest request the server takes, in bytes, and
    `<accepted-types>` the types of file a post can be made from here (the
    engine's, then those of the modules switched on), each with its MIME
    type(s) and usual extensions: hints for a client, to point out at once a
    file that would be refused. The server still decides by the file's
    content.

    `<disk-usage>` is the size of the data directory. It is measured in the
    background and can be up to an hour old; it is null until the first
    measurement after a server start has finished. When several server processes
    run, each measures for itself, so two requests can briefly report different
    sizes.
    """
    post_feature = posts.try_get_current_post_feature()
    ret: dict[str, Any] = {
        "postCount": posts.get_post_count(),
        "diskUsage": _disk_usage.get(),
        "serverTime": util.utcnow(),
        "modules": [module.name for module in registry.modules()],
        "maxUploadSize": max_upload_size(),
        "visibility": visibility.mode(),
        "nsfwTag": visibility.nsfw_tag(),
        "acceptedTypes": [
            {"mime": [mime_type], "extensions": extensions}
            for mime_type, extensions in file_types.accepted_types()
        ],
        "config": {
            "name": config.config["name"],
            "userNameRegex": config.config["user_name_regex"],
            "passwordRegex": config.config["password_regex"],
            "tagNameRegex": config.config["tag_name_regex"],
            "tagCategoryNameRegex": config.config["tag_category_name_regex"],
            "defaultUserRank": config.config["default_rank"],
            "enableSafety": config.config["enable_safety"],
            "contactEmail": config.config["contact_email"],
            "canSendMails": mailer.can_send_mail(),
            "privileges": util.snake_case_to_lower_camel_case_keys(
                config.config["privileges"]
            ),
        },
    }
    if auth.has_privilege(user, "posts:view:featured"):
        ret["featuredPost"] = (
            posts.serialize_post(post_feature.post, user) if post_feature else None
        )
        ret["featuringUser"] = (
            users.serialize_user(post_feature.user, user) if post_feature else None
        )
        ret["featuringTime"] = post_feature.time if post_feature else None
    return ret
