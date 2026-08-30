"""DPYC Oracle — community concierge MCP service."""

# Read from installed package metadata rather than a hand-typed constant.
# This said 0.2.14 while pyproject said 0.3.0 — three releases of drift, including
# two tagged the same morning — so `service_status` reported a version the service
# had not been for weeks. One declaration, in pyproject, is the whole point.
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("dpyc-oracle")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
