class VisualQAError(RuntimeError):
    """Raised when visual QA cannot be completed."""


class LiveGeometryError(RuntimeError):
    """Raised when live geometry cannot be read from the generated PPTX.

    Covers: unreadable PPTX, invalid slide number, missing shape, unreadable
    geometry properties, and invalid slide dimensions.  VisualQAService catches
    this and converts it to VisualQAError before reaching the render/Vision step.
    """
