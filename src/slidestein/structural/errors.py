"""Error types for M10 Structural Recovery."""

from __future__ import annotations


class StructuralRecoveryError(RuntimeError):
    """Raised when structural recovery cannot be completed.

    Pre-provider validation failures carry revision counts of 0.
    """


class StructuralRecoveryExecutionError(StructuralRecoveryError):
    """Raised when an orchestration stage fails after model calls have been made.

    Carries the model_calls dict (attempts made before failure) and the stage
    name so evaluation code can record accurate attempt accounting.
    model_calls reflects counts AT TIME OF FAILURE.
    """

    def __init__(
        self,
        message: str,
        stage: str,
        model_calls: dict,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.model_calls = dict(model_calls)
