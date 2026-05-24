"""Test the actual Settings import."""
try:
    from app.config import settings
    print(f"SUCCESS: provider={settings.llm_provider}")
    print(f"SUCCESS: model={settings.llm_model}")
    print(f"SUCCESS: embedding={settings.embedding_model}")
except Exception as e:
    print(f"ERROR: {e}")
