"""Subprocess entry point for the real background worker integration test."""

import sys
import threading

from lithica import config


def main() -> None:
    config.config["database"] = sys.argv[1]
    config.config["data_dir"] = sys.argv[2]
    config.config["jobs"] = {"poll_interval": 1, "keep_done_days": 7, "worker": False}
    from lithica import registry
    from lithica.func import jobs
    from lithica.tests.fixtures.modules.dummy import module

    registry.use([module])
    stop = threading.Event()
    original = jobs.work_once
    ready = False

    def work() -> bool:
        nonlocal ready
        result = original()
        if not ready:
            print("ready", flush=True)  # noqa: T201 (test process readiness)
            ready = True
        return result

    jobs.work_once = work
    worker = threading.Thread(target=jobs.worker_loop, args=(stop,))
    worker.start()
    try:
        sys.stdin.readline()
    finally:
        stop.set()
        worker.join(timeout=10)
        if worker.is_alive():
            raise RuntimeError("Worker did not stop")


if __name__ == "__main__":
    main()
