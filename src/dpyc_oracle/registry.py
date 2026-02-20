from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RegistryError(Exception):
    """Raised when registry data cannot be fetched or parsed."""


class CommunityRegistry:
    """Cached fetch of dpyc-community repo files from GitHub raw URLs."""

    def __init__(self, base_url: str, cache_ttl_seconds: int = 300) -> None:
        self._base = base_url.rstrip("/")
        self._ttl = cache_ttl_seconds
        self._client = httpx.AsyncClient(timeout=10.0)
        self._json_cache: dict[str, tuple[Any, float]] = {}
        self._text_cache: dict[str, tuple[str, float]] = {}

    async def _fetch_json(self, path: str) -> Any:
        now = time.monotonic()
        if path in self._json_cache:
            data, fetched_at = self._json_cache[path]
            if (now - fetched_at) < self._ttl:
                return data

        url = f"{self._base}/{path}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RegistryError(f"Failed to fetch {url}: {exc}") from exc

        self._json_cache[path] = (data, now)
        return data

    async def _fetch_text(self, path: str) -> str:
        now = time.monotonic()
        if path in self._text_cache:
            text, fetched_at = self._text_cache[path]
            if (now - fetched_at) < self._ttl:
                return text

        url = f"{self._base}/{path}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            text = resp.text
        except httpx.HTTPError as exc:
            raise RegistryError(f"Failed to fetch {url}: {exc}") from exc

        self._text_cache[path] = (text, now)
        return text

    async def get_members(self) -> list[dict[str, Any]]:
        data = await self._fetch_json("members.json")
        try:
            return data["members"]
        except (KeyError, TypeError) as exc:
            raise RegistryError(
                "members.json missing 'members' key"
            ) from exc

    async def get_text(self, path: str) -> str:
        return await self._fetch_text(path)

    async def lookup_member(self, npub: str) -> dict[str, Any] | None:
        members = await self.get_members()
        for member in members:
            if member.get("npub") == npub:
                return member
        return None

    async def get_first_curator(self) -> dict[str, Any] | None:
        members = await self.get_members()
        for member in members:
            if member.get("role") == "prime_authority":
                return member
        return None

    def invalidate_cache(self) -> None:
        self._json_cache.clear()
        self._text_cache.clear()

    async def close(self) -> None:
        await self._client.aclose()
