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
