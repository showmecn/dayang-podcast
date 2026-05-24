"""Dayang Podcast — Application configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Dayang Podcast"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:8088,https://dayang-podcast-frontend.vercel.app"

    # Database
    database_url: str = "postgresql+asyncpg://dayang:dayang@localhost:5432/dayang"

    # Embedding — local model, no API key needed
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # LLM — DeepSeek or local Ollama (company policy: no OpenAI)
    llm_provider: str = "deepseek"            # "deepseek" | "ollama"
    llm_model: str = "deepseek-chat"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Ollama (local LLM, used when llm_provider == "ollama")
    ollama_base_url: str = "http://docker.for.mac.localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b"

    # Podcast Index
    podcast_index_api_key: str = ""
    podcast_index_api_secret: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # Allow extra env vars without crashing
    }


settings = Settings()
