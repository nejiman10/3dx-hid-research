"""Linux SDK implementation of last-successful Report 0x10 suppression."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .report10 import Report10Config


@dataclass(frozen=True)
class CacheSendResult:
    disposition: str
    transport_result: int | None


class Report10SendCache:
    """Cache the last successfully transported 31-byte blob.

    Identical blobs are suppressed.  Success updates the cache.  Any transport
    exception clears it, making the same blob eligible for a later resend.
    This reproduces the recovered policy in the Linux SDK; it does not claim to
    execute or introspect the Windows 3DxWare cache on Linux.
    """

    def __init__(self) -> None:
        self._last_successful_blob: bytes | None = None

    @property
    def last_successful_blob(self) -> bytes | None:
        return self._last_successful_blob

    def clear(self) -> None:
        self._last_successful_blob = None

    def send(
        self,
        config: Report10Config,
        transport: Callable[[bytes], int],
    ) -> CacheSendResult:
        blob = config.to_blob()
        if self._last_successful_blob == blob:
            return CacheSendResult("suppressed-identical", None)
        try:
            result = transport(config.to_wire_report())
        except Exception:
            self.clear()
            raise
        self._last_successful_blob = blob
        return CacheSendResult("sent-and-cached", result)

