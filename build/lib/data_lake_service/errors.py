"""Refusals of a lake host. The names and HTTP mapping are the ones data-gov already consumes."""

from __future__ import annotations


class LakeError(RuntimeError):
    """A refusal that carries a reason the caller can act on."""


class HoldoutError(LakeError):
    """The range reaches into the declared holdout (403)."""


class UnsupportedError(LakeError):
    """The backend cannot serve this operation or this resource shape (422)."""


class UnparseableError(LakeError):
    """The bytes exist but cannot be parsed under the declared contract (422)."""


class BackendRefusal(LakeError):
    """The backend refused to start or to answer: configuration, not a caller error."""


class DiscoveryRefusal(BackendRefusal):
    """The configured backend could not be resolved to one installed, named distribution."""


#: How a refusal reaches the caller. A provider is an independently packaged distribution:
#: it may import these classes, or stay decoupled and mark its own exception with
#: `refusal = "HOLDOUT" | "UNSUPPORTED" | "UNPARSEABLE" | "NOT_FOUND" | "BAD_RANGE"`.
#: Providers ported from the existing plugins raise same-named classes of their own module,
#: so those names are recognised too. Anything unrecognised stays a 500: a host does not
#: turn a defect into a polite refusal.
REFUSAL_STATUS = {"HOLDOUT": 403, "NOT_FOUND": 404, "UNSUPPORTED": 422,
                  "UNPARSEABLE": 422, "BAD_RANGE": 400}

_BY_CLASS_NAME = {"HoldoutError": "HOLDOUT", "UnsupportedError": "UNSUPPORTED",
                  "UnparseableError": "UNPARSEABLE", "LakeError": "BAD_RANGE"}


def classify(exc: BaseException) -> str | None:
    """The refusal kind of a backend exception, or None when the host must not answer for it."""
    if isinstance(exc, HoldoutError):
        return "HOLDOUT"
    if isinstance(exc, (UnsupportedError, UnparseableError)):
        return "UNSUPPORTED" if isinstance(exc, UnsupportedError) else "UNPARSEABLE"
    if isinstance(exc, FileNotFoundError):
        return "NOT_FOUND"
    if isinstance(exc, LakeError):
        return "BAD_RANGE"
    declared = getattr(exc, "refusal", None)
    if isinstance(declared, str) and declared in REFUSAL_STATUS:
        return declared
    for klass in type(exc).__mro__:
        kind = _BY_CLASS_NAME.get(klass.__name__)
        if kind:
            return kind
    if isinstance(exc, ValueError):
        return "BAD_RANGE"
    return None
