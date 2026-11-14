"""
Run the scheduled jobs in their own process, separate from the web workers.

    python scheduler_main.py

Then start the web workers with SCHEDULER_MODE=off, so they do not run jobs:

    SCHEDULER_MODE=off gunicorn run:app --bind 0.0.0.0:$PORT

Running both ways at once is also safe — every job runs only once — but one
scheduler process is simpler to watch and keeps job work off the web workers.
Stop with Ctrl+C or SIGTERM (systemd / Docker stop); running jobs are allowed
to finish.
"""

import logging
import os
import signal
import threading

# the web app inside this process must not start a second scheduler
os.environ["SCHEDULER_MODE"] = "off"

from app import create_app  # noqa: E402
from app.scheduler import init_scheduler  # noqa: E402

log = logging.getLogger("scheduler_main")


def main():
    app = create_app()
    scheduler = init_scheduler(app, force=True)

    stop = threading.Event()

    def _stop(signum, _frame):
        log.info("Signal %s received — stopping scheduler", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info("Scheduler process running (pid %s)", os.getpid())
    while not stop.wait(3600):
        pass
    scheduler.shutdown(wait=True)
    log.info("Scheduler stopped")


if __name__ == "__main__":
    main()
