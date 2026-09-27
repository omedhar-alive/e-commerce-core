"""The running core version, from package metadata (W3)."""

from importlib.metadata import PackageNotFoundError, version


def core_version() -> str:
    try:
        return version("commerce-core")
    except PackageNotFoundError:
        return "unknown"
