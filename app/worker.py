from __future__ import annotations

import signal
import time

from .job_queue import worker
from .models import init_db


stopping = False


def stop_worker(*_: object) -> None:
    global stopping
    stopping = True
    worker.stop()


if __name__ == "__main__":
    init_db()
    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    worker.start()
    while not stopping:
        time.sleep(1)
