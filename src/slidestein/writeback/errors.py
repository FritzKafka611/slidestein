"""M6 error type for PowerPoint write-back failures."""

from __future__ import annotations


class PowerPointWritebackError(RuntimeError):
    """Raised when a write-back operation fails.

    The message must identify slide, slot_id, shape_path, and reason.
    Must never expose credentials or unrelated environment values.
    """
