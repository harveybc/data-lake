"""The backend interface of a lake host.

A host serves the HTTP contract; a backend owns the data. The host never guesses
what a backend can do: a backend declares its capabilities and the host answers
422 for everything it did not declare, instead of inventing a plausible reply.
"""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from .errors import UnsupportedError

#: Every operation a lake host can expose. A backend declares a subset.
CAPABILITIES = (
    "describe",       # identity and metadata of the store
    "storage",        # bytes on the host
    "discover",       # the resource inventory
    "coverage",       # the time coverage of one resource
    "read",           # a bounded row window, as JSON
    "download",       # the ungoverned delivery of bytes
    "governed_download",  # the delivery under an availability contract, with its identity
    "write_metrics",  # accept a report back from a consumer
)


@runtime_checkable
class LakeBackend(Protocol):
    """What a provider package registers under the `datalake.backends` entry-point group."""

    def capabilities(self) -> Iterable[str]: ...

    def set_params(self, **settings) -> None: ...

    def describe(self) -> dict: ...


class LakeBackendBase:
    """Optional base class: declares nothing, refuses everything, and records its settings.

    A provider overrides what it supports and lists it in `declared_capabilities`.
    Inheriting is not required; the host only needs the methods a capability names.
    """

    declared_capabilities: tuple = ()
    backend_params: dict = {}

    def __init__(self):
        self.params = dict(self.backend_params)

    # -- configuration -------------------------------------------------
    def set_params(self, **settings):
        self.params.update(settings)

    def capabilities(self):
        return tuple(self.declared_capabilities)

    def source_identity(self) -> dict:
        """Where this backend's code comes from. Recorded by the host, never trusted as policy."""
        return {}

    # -- operations ----------------------------------------------------
    def _refuse(self, name):
        raise UnsupportedError(f"this backend does not support {name}")

    def sweep(self):
        return None

    def describe(self):
        self._refuse("describe")

    def storage(self):
        self._refuse("storage")

    def discover(self):
        self._refuse("discover")

    def coverage(self, resource_id):
        self._refuse("coverage")

    def read(self, resource_id, start=None, end=None):
        self._refuse("read")

    def download(self, resource_id, start=None, end=None):
        self._refuse("download")

    def governed_download(self, resource_id, start=None, end=None):
        self._refuse("governed_download")

    def write_metrics(self, report: dict):
        self._refuse("write_metrics")

    def is_spool(self, path) -> bool:
        return False


def check_capabilities(declared) -> tuple:
    declared = tuple(declared or ())
    unknown = [c for c in declared if c not in CAPABILITIES]
    if unknown:
        raise UnsupportedError(f"a backend declares unknown capabilities: {sorted(unknown)}")
    return declared
