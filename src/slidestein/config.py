from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Optional at startup so that index/status work without a key.
    # Commands that call the Anthropic API must validate it themselves.
    anthropic_api_key: Optional[str] = None

    slides_dir: Path = Path("data/slides")
    output_dir: Path = Path("data/output")
    previews_dir: Path = Path("data/previews")
    db_path: Path = Path("data/slidestein.db")
    lancedb_uri: str = "data/lancedb"

    generation_model: str = "claude-sonnet-4-6"
    vision_model: str = "claude-opus-4-5"
    classification_model: str = "claude-opus-4-5"

    # Classification provider: "anthropic" or "sap_ai_core"
    classification_provider: str = "anthropic"

    # SAP AI Core / Generative AI Hub credentials (loaded from .env)
    aicore_auth_url: Optional[str] = None
    aicore_client_id: Optional[str] = None
    aicore_client_secret: Optional[str] = None
    aicore_base_url: Optional[str] = None
    aicore_resource_group: str = "default"
    sap_ai_core_model: str = "claude-3.5-sonnet"

    # Embedding provider: "sap_ai_core"
    embedding_provider: str = "sap_ai_core"
    sap_ai_core_embedding_model: str = "text-embedding-3-large"

    # Vision reranking provider: "sap_ai_core"
    vision_rerank_provider: str = "sap_ai_core"

    # Slide brief generation provider: "sap_ai_core"
    slide_brief_provider: str = "sap_ai_core"

    # Slot analysis provider (M5.2): "sap_ai_core"
    slot_analysis_provider: str = "sap_ai_core"

    # Content draft provider (M5.3): "sap_ai_core"
    content_draft_provider: str = "sap_ai_core"

    # Manager review provider (M7): "sap_ai_core"
    manager_review_provider: str = "sap_ai_core"

    # Visual QA provider (M8): "sap_ai_core"
    visual_qa_provider: str = "sap_ai_core"
    # sap_ai_core_model (shared with reranking/briefing/classification) is the
    # model used for all SAP AI Core Orchestration V2 calls including slot
    # analysis Vision.  sap_ai_core_vision_model was removed (was unused and
    # caused confusion during evaluation).

    sap_ai_core_base_url: Optional[str] = None
    sap_ai_core_client_id: Optional[str] = None
    sap_ai_core_client_secret: Optional[str] = None
    sap_ai_core_auth_url: Optional[str] = None
    sap_ai_core_resource_group: str = "default"

    # PPT Master integration (Milestone 2.5+)
    # pptmaster_python: set to the Python inside tools/pptmaster-env/ or leave
    # None for auto-discovery (looks for tools/pptmaster-env/Scripts/python.exe).
    pptmaster_python: Optional[Path] = None
    pptmaster_workspace_root: Path = Path("outputs/workspaces")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


def get_settings() -> Settings:
    return Settings()
