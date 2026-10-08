"""Phase A smoke test — one real SAP AI Core request on slide 3.

Run from repo root:
    .venv/Scripts/python.exe scripts/smoke_test_sap.py

Reports: provider / model / deployment / slide / latency / parsed profile.
Never prints credentials, tokens, or secrets.
"""

import sys
import time
from pathlib import Path

# Repo root on sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from slidestein.config import get_settings
from slidestein.classification.providers.factory import _build_sap_classifier
from slidestein.domain.models import SlideClassificationInput
import sqlite3


def main():
    settings = get_settings()

    print("[smoke] provider          : sap_ai_core")
    print(f"[smoke] model             : {settings.sap_ai_core_model}")
    print(f"[smoke] auth_url present  : {'yes' if settings.aicore_auth_url else 'no'}")
    print(f"[smoke] client_id present : {'yes' if settings.aicore_client_id else 'no'}")
    print(f"[smoke] secret present    : {'yes' if settings.aicore_client_secret else 'no'}")
    print(f"[smoke] base_url present  : {'yes' if settings.aicore_base_url else 'no'}")

    # Build classifier (authenticates lazily on first request)
    classifier = _build_sap_classifier(settings)

    # Load slide 3 data from the indexed DB
    db_path = ROOT / settings.db_path
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT slide_id, extracted_text, shape_count, slide_number, preview_path "
        "FROM slide_records WHERE slide_number=3 LIMIT 1"
    ).fetchone()
    conn.close()

    if row is None:
        print("[smoke] ERROR: slide 3 not indexed. Run 'index' first.")
        sys.exit(1)

    slide_id = row["slide_id"]
    preview = ROOT / row["preview_path"]

    print(f"[smoke] slide_number      : {row['slide_number']}")
    print(f"[smoke] slide_id          : {slide_id}")
    print(f"[smoke] preview           : {preview}")
    print(f"[smoke] preview exists    : {'yes' if preview.exists() else 'no'}")

    structural_metadata = {
        "slide_number": row["slide_number"],
        "shape_count": row["shape_count"],
    }

    classification_input = SlideClassificationInput(
        slide_id=slide_id,
        extracted_text=row["extracted_text"] or "",
        structural_metadata=structural_metadata,
        preview_path=preview if preview.exists() else None,
    )

    print("[smoke] sending request to SAP AI Core Orchestration V2...")
    t0 = time.perf_counter()
    try:
        profile = classifier.classify(classification_input)
    except Exception as exc:
        print(f"[smoke] FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)
    elapsed = time.perf_counter() - t0

    deployment_id = getattr(classifier, "_deployment_id_cache", "unknown")

    print()
    print("=" * 60)
    print("SMOKE TEST PASSED")
    print("=" * 60)
    print(f"  provider                : sap_ai_core")
    print(f"  model                   : {settings.sap_ai_core_model}")
    print(f"  orchestration deploy ID : {deployment_id}")
    print(f"  slide_number            : {row['slide_number']}")
    print(f"  latency                 : {elapsed:.2f}s")
    print()
    print("  Parsed SlideSemanticProfile:")
    print(f"    slide_id              : {profile.slide_id}")
    print(f"    schema_version        : {profile.schema_version}")
    print(f"    primary_comm_job      : {profile.primary_communication_job}")
    print(f"    secondary_comm_jobs   : {profile.secondary_communication_jobs}")
    print(f"    storyline_roles       : {profile.storyline_roles}")
    print(f"    visual_archetype      : {profile.visual_archetype}")
    print(f"    density               : {profile.density}")
    print(f"    structural_pattern    : {profile.structural_pattern}")
    print(f"    description (50 chars): {str(profile.description)[:50]}")
    print(f"    best_for              : {profile.best_for}")
    print(f"    not_for               : {profile.not_for}")
    print()
    print("Phase A complete. Ready for Phase B.")
    sys.exit(0)


if __name__ == "__main__":
    main()
