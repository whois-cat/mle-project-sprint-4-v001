from functools import lru_cache
from config import CFG
from pydantic_settings import BaseSettings, SettingsConfigDict

class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    reload_token: str | None = None
    redis_url: str | None = None

    redis_timeout_seconds: float = 0.2
    cache_ttl_seconds: int = 3600

    online_keep: int = 200
    online_history_take: int = 10
    online_take: int = 3

    service_cache_topn: int = CFG.K_CANDIDATES
    similar_per_track: int = 30

    weight_ranked: float = 1.0
    weight_similar_online: float = 0.7
    weight_personal: float = 0.6
    weight_popular: float = 0.2

    recommend_rate_limit: str = "60/minute"
    metrics_path: str = "/metrics"

    popular_pool_multiplier: int = 50
    popular_pool_min: int = 500


@lru_cache
def get_settings() -> ServiceSettings:
    return ServiceSettings()
