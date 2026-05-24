"""Test configuration for pytest."""

from __future__ import annotations

import os
import sys

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override settings for testing
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("LOG_LEVEL", "CRITICAL")
os.environ.setdefault("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
