class RevisionError(RuntimeError):
    """Raised when bounded revision cannot be completed."""


class RevisionExecutionError(RevisionError):
    """Raised when an orchestration stage fails after model calls have been made.

    Carries the model_calls dict (attempts made before failure) and the stage
    name, so evaluation code can record accurate attempt accounting.

    model_calls reflects counts BEFORE the failure, not counts of successes.
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
