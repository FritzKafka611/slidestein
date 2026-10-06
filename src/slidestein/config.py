from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str

    slides_dir: Path = Path("data/slides")
    output_dir: Path = Path("data/output")
    db_path: Path = Path("data/slidestein.db")
    lancedb_uri: str = "data/lancedb"

    generation_model: str = "claude-sonnet-4-6"
    vision_model: str = "claude-opus-4-5"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


def get_settings() -> Settings:
    return Settings()
