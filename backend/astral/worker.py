"""Standalone worker process: ``python -m astral.worker``."""

from __future__ import annotations

import logging
import signal

from .services.jobs import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> None:
    w = Worker()
    signal.signal(signal.SIGTERM, lambda *_: w.stop())
    signal.signal(signal.SIGINT, lambda *_: w.stop())
    logging.getLogger("astral.worker").info("worker %s started", w.worker_id)
    w.run_forever()


if __name__ == "__main__":
    main()
