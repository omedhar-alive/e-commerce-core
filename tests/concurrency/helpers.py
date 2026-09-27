"""Real-connection concurrency (phase plan section 4, item 7).

Each worker runs in its own thread with its own database connection, and all
workers are released together by a barrier just before the contended write.
"""

import threading

from django.db import connection


def run_concurrently(*workers, timeout: float = 30):
    """Run each callable in its own thread. ``barrier.wait()`` is passed in.

    Returns a list of (result, exception) per worker, in order.
    """
    barrier = threading.Barrier(len(workers), timeout=timeout)
    outcomes: list = [None] * len(workers)

    def target(index, fn):
        try:
            outcomes[index] = (fn(barrier), None)
        except BaseException as exc:  # recorded for the test to assert on
            outcomes[index] = (None, exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=target, args=(i, fn)) for i, fn in enumerate(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    return outcomes
