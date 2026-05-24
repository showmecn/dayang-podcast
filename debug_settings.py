"""Debug script for Settings class."""
from pydantic_settings import BaseSettings

class Test(BaseSettings):
    deepseek_api_key: str = ""
    llm_model: str = "deepseek-chat"
    model_config = {"env_file": ".env"}

t = Test()
print(f"deepseek_key={t.deepseek_api_key!r}")
print(f"model={t.llm_model!r}")
