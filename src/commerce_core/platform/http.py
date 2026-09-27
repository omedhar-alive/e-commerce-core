"""The shared HTTP client: the only way core calls out (T1, T4).

* Connect, read, write and pool timeouts are always set; they cannot be
  switched off.
* Calling it inside ``transaction.atomic()`` raises ``HttpInsideTransaction``
  before any request is made: commit first, then call, then record the result
  in a second transaction (T1).
* No other module imports an HTTP library (import-linter, W8a).
"""

import httpx
from django.db import connections

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)


class HttpInsideTransaction(RuntimeError):
    pass


class TimeoutRequired(ValueError):
    pass


def in_transaction() -> bool:
    return any(conn.in_atomic_block for conn in connections.all(initialized_only=True))


def _check_timeout(timeout: httpx.Timeout) -> None:
    if None in (timeout.connect, timeout.read, timeout.write, timeout.pool):
        raise TimeoutRequired("every HTTP timeout must be set (T4)")


class HttpClient:
    def __init__(self, *, timeout: httpx.Timeout = DEFAULT_TIMEOUT, **kwargs):
        _check_timeout(timeout)
        if "transport" in kwargs and kwargs["transport"] is None:
            kwargs.pop("transport")
        self._client = httpx.Client(timeout=timeout, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if in_transaction():
            raise HttpInsideTransaction(
                "outbound HTTP inside transaction.atomic() (T1): commit first, then call"
            )
        if "timeout" in kwargs:
            timeout = kwargs["timeout"]
            _check_timeout(
                timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
            )
        return self._client.request(method, url, **kwargs)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# Transport errors callers may need to catch without importing httpx.
TransportError = httpx.TransportError
