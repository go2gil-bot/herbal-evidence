"""Runtime configuration, read from the environment.

Secrets never have defaults and are never logged. Anything with a default here
is safe to print.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolved from this file rather than the working directory, so the service finds
# its own .env whether it is started from backend/, from the repo root, or by a
# process manager with a different cwd. In the container there is no .env at all
# and every value comes from the environment.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_env: Literal["dev", "production"] = "dev"
    port: int = 8000
    log_level: str = "INFO"

    # Supabase - public
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_jwt_issuer: str = ""

    # Supabase - secret, server only
    supabase_secret_key: str = Field(default="", repr=False)

    # CORS: exact origins, comma separated. No wildcards.
    cors_allowed_origins: str = ""
    frontend_origin: str = ""

    # AI provider - configured later; missing key is a blocked integration,
    # never a reason to emit mock research output.
    ai_provider: str = "none"
    ai_model: str = ""
    ai_api_key: str = Field(default="", repr=False)

    ncbi_api_key: str = Field(default="", repr=False)
    # NCBI asks callers to identify themselves. Not hardcoded: sending someone's
    # address to a third party is their decision, so it stays configuration.
    ncbi_contact_email: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        raw = self.cors_allowed_origins or self.frontend_origin
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
