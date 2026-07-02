"""ARGUS Copilot — central settings (Task 41).

Single source of truth for ALL environment configuration. 12-factor:
identical code across dev/CI/cluster; behavior differs only via env (or .env).

Env matrix (see .env.example):
  ARGUS_FAST=1            fast mode: small startup ensemble/bands (dev) | 0 = full fidelity
  ARGUS_SEED=42           global simulation seed (manifests embed it)
  ARGUS_DB=/tmp/argus/copilot.db   SQLite path (used only when DATABASE_URL unset)
  DATABASE_URL=postgresql://...    switches persistence to PostgreSQL (store_pg)
  ARGUS_THETA_CACHE=<path>         deployed-theta JSON cache override
  ARGUS_CORS_ORIGINS=*             comma-separated allowed origins
  OLLAMA_URL=http://...:11434      optional NLU parse assist (never produces numbers)
  OLLAMA_MODEL=llama3.1            model name for the assist

Usage:  from services.copilot.config import get_settings
        s = get_settings()          # cached; call sites read at runtime, not import
"""
from __future__ import annotations
import os
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARGUS_", env_file=".env", extra="ignore")

    # -- runtime / engines ----------------------------------------------------
    fast: bool = True                                  # ARGUS_FAST
    seed: int = 42                                     # ARGUS_SEED
    theta_cache: str = os.path.join(_ROOT, "output", "theta_deployed.json")  # ARGUS_THETA_CACHE
    engine_shards: int = 1                             # ARGUS_ENGINE_SHARDS (Task 82; >1 = parallel slices)

    # -- persistence ------------------------------------------------------------
    db: str = "/tmp/argus/copilot.db"                  # ARGUS_DB (sqlite; local disk — not a network mount)
    database_url: str | None = Field(                  # DATABASE_URL (unprefixed, conventional)
        default=None, validation_alias=AliasChoices("DATABASE_URL", "ARGUS_DATABASE_URL"))

    # -- NLU assist (optional; parse-only, never numbers) -------------------------
    ollama_url: str | None = Field(
        default=None, validation_alias=AliasChoices("OLLAMA_URL", "ARGUS_OLLAMA_URL"))
    ollama_model: str = Field(
        default="llama3.1", validation_alias=AliasChoices("OLLAMA_MODEL", "ARGUS_OLLAMA_MODEL"))

    # -- LLM service (Task 76; OpenAI-compatible vLLM; preferred over Ollama when set) --
    llm_base_url: str | None = Field(                  # e.g. http://vllm:8000/v1
        default=None, validation_alias=AliasChoices("ARGUS_LLM_URL", "OPENAI_BASE_URL", "VLLM_URL"))
    llm_model: str = Field(                            # PINNED model id (revision pinned in deploy)
        default="Qwen2.5-1.5B-Instruct",
        validation_alias=AliasChoices("ARGUS_LLM_MODEL", "OPENAI_MODEL", "VLLM_MODEL"))
    llm_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ARGUS_LLM_API_KEY", "OPENAI_API_KEY"))
    llm_max_tokens: int = 64                           # ARGUS_LLM_MAX_TOKENS (NLU emits a tiny JSON)
    llm_timeout: float = 10.0                          # ARGUS_LLM_TIMEOUT (seconds)

    # -- counterfactual cache (Task 85) ------------------------------------------
    redis_url: str | None = Field(                     # enables Redis-backed cf cache
        default=None, validation_alias=AliasChoices("ARGUS_REDIS_URL", "REDIS_URL"))
    cf_cache_size: int = 256                           # ARGUS_CF_CACHE_SIZE (in-process LRU)
    cf_cache_ttl: int = 3600                            # ARGUS_CF_TTL (Task 98: Redis entry TTL, s)
    entailment_enforce: bool = False                   # ARGUS_ENTAILMENT_ENFORCE (Task 77: block unfaithful sentences)

    # -- ingestion credentials (optional; workers skip live mode without them) ----
    acled_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ACLED_KEY", "ARGUS_ACLED_KEY"))
    acled_email: str | None = Field(
        default=None, validation_alias=AliasChoices("ACLED_EMAIL", "ARGUS_ACLED_EMAIL"))

    # -- knowledge graph (optional; loader emits cypher file when unset) ----------
    neo4j_uri: str | None = Field(
        default=None, validation_alias=AliasChoices("NEO4J_URI", "ARGUS_NEO4J_URI"))
    neo4j_user: str = Field(
        default="neo4j", validation_alias=AliasChoices("NEO4J_USER", "ARGUS_NEO4J_USER"))
    neo4j_password: str | None = Field(
        default=None, validation_alias=AliasChoices("NEO4J_PASSWORD", "ARGUS_NEO4J_PASSWORD"))

    # -- gateway / auth (Task 74; OIDC/JWT). Disabled by default (dev/back-compat). ---
    auth_enabled: bool = False                         # ARGUS_AUTH_ENABLED
    jwt_secret: str = "dev-insecure-secret-change-me"  # ARGUS_JWT_SECRET (HS256 dev signing)
    jwt_algorithms: str = "HS256"                      # ARGUS_JWT_ALGORITHMS (comma-sep; RS256 for OIDC)
    jwt_issuer: str | None = Field(                    # expected `iss` (OIDC provider)
        default=None, validation_alias=AliasChoices("ARGUS_JWT_ISSUER", "OIDC_ISSUER"))
    jwt_audience: str | None = Field(                  # expected `aud`
        default=None, validation_alias=AliasChoices("ARGUS_JWT_AUDIENCE", "OIDC_AUDIENCE"))
    jwks_url: str | None = Field(                      # RS256 key set (OIDC); enables JWKS path
        default=None, validation_alias=AliasChoices("ARGUS_JWKS_URL", "OIDC_JWKS_URL"))
    clearance_claim: str = "clearance"                 # ARGUS_CLEARANCE_CLAIM (claim carrying clearance)
    auth_dev_clearance: str = "SECRET"                 # ARGUS_AUTH_DEV_CLEARANCE (principal when auth disabled)
    dlp_enforce: bool = True                           # ARGUS_DLP_ENFORCE (Task 91: egress DLP gate)
    dlp_canaries: str = ""                             # ARGUS_DLP_CANARIES (comma-separated leak canaries)

    # -- service -------------------------------------------------------------------
    cors_origins: str = "*"                            # ARGUS_CORS_ORIGINS (comma-separated)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def backend(self) -> str:
        return "postgres" if self.database_url else "sqlite"

    @property
    def jwt_algorithm_list(self) -> list[str]:
        return [a.strip() for a in self.jwt_algorithms.split(",") if a.strip()]

    @property
    def dlp_canary_list(self) -> list[str]:
        return [c.strip() for c in self.dlp_canaries.split(",") if c.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test helper: force re-read of environment on next get_settings()."""
    get_settings.cache_clear()
