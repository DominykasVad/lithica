import os
import threading
from datetime import datetime, timedelta

from lithica import config, rest
from lithica.func import auth, posts, users, util

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
            threading.Thread(target=self._measure, daemon=True).start()
        with self._lock:
            return self._value

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


@rest.routes.get("/info/?")
def get_info(ctx: rest.Context, _params: dict[str, str] | None = None) -> rest.Response:
    if _params is None:
        _params = {}
    post_feature = posts.try_get_current_post_feature()
    ret = {
        "postCount": posts.get_post_count(),
        "diskUsage": _disk_usage.get(),
        "serverTime": util.utcnow(),
        "config": {
            "name": config.config["name"],
            "userNameRegex": config.config["user_name_regex"],
            "passwordRegex": config.config["password_regex"],
            "tagNameRegex": config.config["tag_name_regex"],
            "tagCategoryNameRegex": config.config["tag_category_name_regex"],
            "defaultUserRank": config.config["default_rank"],
            "enableSafety": config.config["enable_safety"],
            "contactEmail": config.config["contact_email"],
            "canSendMails": bool(config.config["smtp"]["host"]),
            "privileges": util.snake_case_to_lower_camel_case_keys(
                config.config["privileges"]
            ),
        },
    }
    if auth.has_privilege(ctx.user, "posts:view:featured"):
        ret["featuredPost"] = (
            posts.serialize_post(post_feature.post, ctx.user) if post_feature else None
        )
        ret["featuringUser"] = (
            users.serialize_user(post_feature.user, ctx.user) if post_feature else None
        )
        ret["featuringTime"] = post_feature.time if post_feature else None
    return ret
