MANAGER_REVIEW_SCHEMA_VERSION = "1.1"
# 1.0: initial manager review
# 1.1: added slide_id/deck_id/slide_number; factual_flags now list[ManagerReviewIssue]

MANAGER_REVIEW_PROMPT_VERSION = "1.1"
# 1.0: initial manager review
# 1.1: qualitative recommendation, communication-job-aware title rubric,
#       body-based exhibit consistency, MECE boundary, clear-slot semantics,
#       capacity/group context, original_request, prompt-injection hardening
