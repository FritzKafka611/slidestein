"""Classification and prompt version constants.

Bump CLASSIFICATION_VERSION when the taxonomy or Pydantic model changes in a
way that makes old stored profiles incompatible.  Bump PROMPT_VERSION when the
prompt changes enough to produce materially different output.

Both values form part of the input_fingerprint that drives staleness detection.
"""

CLASSIFICATION_VERSION = "1.0"
PROMPT_VERSION = "1.0"
