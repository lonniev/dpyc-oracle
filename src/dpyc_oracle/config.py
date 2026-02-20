from __future__ import annotations

from pydantic_settings import BaseSettings


class OracleSettings(BaseSettings):
    dpyc_community_base_url: str = (
        "https://raw.githubusercontent.com/lonniev/dpyc-community/main"
    )
    cache_ttl_seconds: int = 300
