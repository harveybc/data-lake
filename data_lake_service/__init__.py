"""A reusable lake host: the HTTP contract and the backend seam, with no data of its own."""

from .backends import CAPABILITIES, LakeBackendBase
from .errors import (BackendRefusal, DiscoveryRefusal, HoldoutError, LakeError,
                     UnparseableError, UnsupportedError)

__all__ = ["CAPABILITIES", "LakeBackendBase", "LakeError", "HoldoutError", "UnsupportedError",
           "UnparseableError", "BackendRefusal", "DiscoveryRefusal", "__version__"]
__version__ = "0.1.0"
