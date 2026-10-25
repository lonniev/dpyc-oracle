from __future__ import annotations

from pydantic_settings import BaseSettings


class OracleSettings(BaseSettings):
    dpyc_community_base_url: str = (
        "https://raw.githubusercontent.com/lonniev/dpyc-community/main"
    )
    cache_ttl_seconds: int = 300
    github_token: str | None = None
    dpyc_community_repo: str = "lonniev/dpyc-community"
    # Ranks the Lightning wallets offered to new guests. Unset: catalog order.
    brave_search_api_key: str | None = None
    wallets_ttl_seconds: int = 86400
