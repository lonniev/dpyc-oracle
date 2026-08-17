from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# After a failed refresh, wait this long before hitting the network again for
# that path (serving the stale copy meanwhile) so an upstream outage can't turn
# into a fetch on every single call. The Oracle is the fleet's bootstrap
# chokepoint now — it must degrade, not fail closed.
_FAIL_BACKOFF_SECONDS = 60.0


class RegistryError(Exception):
    """Raised when registry data cannot be fetched or parsed AND no cached copy exists."""


class CommunityRegistry:
    """Cached fetch of dpyc-community repo files.

    Reads via the authenticated GitHub **contents API** when a token is present
    (5,000 req/hr, raw media type — no base64 dance), else falls back to
    anonymous ``raw.githubusercontent.com``. On any refresh failure a
    previously-fetched copy is served (stale-if-error) with a short backoff, so
    a GitHub hiccup degrades to slightly-stale answers instead of a hard outage.
    """

    def __init__(
        self,
        base_url: str,
        cache_ttl_seconds: int = 300,
        repo: str | None = None,
        github_token: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._ttl = cache_ttl_seconds
        self._repo = repo
        self._token = github_token
        self._client = httpx.AsyncClient(timeout=10.0)
        # path -> (value, fetched_at_monotonic)
        self._json_cache: dict[str, tuple[Any, float]] = {}
        self._text_cache: dict[str, tuple[str, float]] = {}
        # path -> monotonic time before which we won't retry after a failure
        self._retry_after: dict[str, float] = {}

    async def _raw_get(self, path: str) -> httpx.Response:
        """GET a repo file, preferring the authenticated contents API.

        With a token, the contents API (5,000 req/hr) is asked for the raw
        media type, so ``.text``/``.json()`` work exactly as they do against
        ``raw.githubusercontent.com`` — no base64 decode. Anonymous raw is the
        fallback when no token is configured.
        """
        if self._token and self._repo:
            resp = await self._client.get(
                f"https://api.github.com/repos/{self._repo}/contents/{path}?ref=main",
                headers={
                    "Accept": "application/vnd.github.raw",
                    "Authorization": f"Bearer {self._token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        else:
            resp = await self._client.get(f"{self._base}/{path}")
        resp.raise_for_status()
        return resp

    async def _fetch(
        self,
        path: str,
        cache: dict[str, tuple[Any, float]],
        extract,
    ) -> Any:
        now = time.monotonic()

        # Fresh cache — return without touching the network.
        if path in cache and (now - cache[path][1]) < self._ttl:
            return cache[path][0]

        # Stale cache but inside the post-failure backoff window — serve stale.
        if path in cache and now < self._retry_after.get(path, 0.0):
            return cache[path][0]

        try:
            value = extract(await self._raw_get(path))
        except (httpx.HTTPError, ValueError) as exc:
            cached = cache.get(path)
            if cached is not None:
                logger.warning(
                    "Registry refresh failed for %s (%s); serving last-known-good.",
                    path, exc,
                )
                self._retry_after[path] = now + _FAIL_BACKOFF_SECONDS
                return cached[0]
            raise RegistryError(f"Failed to fetch {path}: {exc}") from exc

        cache[path] = (value, now)
        self._retry_after.pop(path, None)
        return value

    async def _fetch_json(self, path: str) -> Any:
        return await self._fetch(path, self._json_cache, lambda r: r.json())

    async def _fetch_text(self, path: str) -> str:
        return await self._fetch(path, self._text_cache, lambda r: r.text)

    async def get_members(self) -> list[dict[str, Any]]:
        data = await self._fetch_json("members/read-only-lookup-cache.json")
        try:
            return data["members"]
        except (KeyError, TypeError) as exc:
            raise RegistryError(
                "read-only-lookup-cache.json missing 'members' key"
            ) from exc

    async def get_text(self, path: str) -> str:
        return await self._fetch_text(path)

    async def lookup_member(self, npub: str) -> dict[str, Any] | None:
        members = await self.get_members()
        for member in members:
            if member.get("npub") == npub:
                return member
        return None

    async def get_network_status(self) -> dict[str, Any]:
        return await self._fetch_json("network-status.json")

    async def get_first_curator(self) -> dict[str, Any] | None:
        members = await self.get_members()
        for member in members:
            if member.get("role") == "prime_authority":
                return member
        return None

    # --- Bootstrap-support resolvers (so Operators never read GitHub) ---------

    async def get_relays(self) -> list[str]:
        """Return the DPYC Nostr relay set, primary-first, deduped.

        Serves ``relays.json`` from the dpyc-community repo root — the same
        single source of truth the SDK used to fetch from GitHub directly.
        Operators now obtain it here via one MCP call instead.
        """
        data = await self._fetch_json("relays.json")
        entries = data.get("relays") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise RegistryError("relays.json missing a 'relays' list.")
        primary: list[str] = []
        rest: list[str] = []
        for entry in entries:
            if isinstance(entry, dict):
                url = entry.get("url")
                is_primary = bool(entry.get("primary"))
            elif isinstance(entry, str):
                url, is_primary = entry, False
            else:
                continue
            if not isinstance(url, str) or not url.startswith("wss://"):
                continue
            (primary if is_primary else rest).append(url)
        ordered: list[str] = []
        for url in primary + rest:
            if url not in ordered:
                ordered.append(url)
        if not ordered:
            raise RegistryError("relays.json contained no valid wss:// relays.")
        return ordered

    async def resolve_authority_for(self, operator_npub: str) -> dict[str, str] | None:
        """Return the certifying Authority ``{npub, url, name}`` for an operator.

        Reads the operator's ``upstream_authority_npub`` and returns that
        Authority's first registered service. ``None`` if the operator is
        unknown, has no upstream (a trust root), or the Authority lists no
        service.
        """
        member = await self.lookup_member(operator_npub)
        if member is None:
            return None
        upstream = member.get("upstream_authority_npub")
        if not upstream:
            return None
        authority = await self.lookup_member(upstream)
        if authority is None:
            return None
        services = authority.get("services") or []
        if not services:
            return {"npub": upstream, "url": "", "name": authority.get("display_name", "")}
        svc = services[0]
        return {
            "npub": upstream,
            "url": svc.get("url", ""),
            "name": svc.get("name", authority.get("display_name", "")),
        }

    async def purchase_mode(self, npub: str) -> str:
        """Derive ``"certified"`` or ``"direct"`` from the registry chain.

        Mirrors the SDK's topology rule: a trust root, or an actor whose parent
        is itself Prime (runs no certify MCP), self-funds → ``"direct"``; an
        actor under a non-Prime Authority pays its parent → ``"certified"``.
        Unknown npub → ``"direct"`` (fail safe: never assert a certify hop that
        isn't there).
        """
        members = await self.get_members()
        by_npub = {m.get("npub"): m for m in members}
        me = by_npub.get(npub)
        if me is None:
            return "direct"
        parent_npub = me.get("upstream_authority_npub")
        if not parent_npub:
            return "direct"
        parent = by_npub.get(parent_npub)
        if parent is None or not parent.get("upstream_authority_npub"):
            return "direct"
        return "certified"

    async def resolve_service(
        self, name: str | None = None, npub: str | None = None
    ) -> dict[str, str] | None:
        """Resolve a service by ``name`` or ``npub`` → ``{npub, url, name, role, purchase_mode}``.

        By npub: the member's first service. By name: the first active member
        whose ``services[]`` carries that name. ``None`` if not found.
        """
        members = await self.get_members()
        if npub is not None:
            member = next((m for m in members if m.get("npub") == npub), None)
            if member is None:
                return None
            services = member.get("services") or []
            svc = services[0] if services else {}
            return {
                "npub": npub,
                "url": svc.get("url", ""),
                "name": svc.get("name", member.get("display_name", "")),
                "role": member.get("role", ""),
                "purchase_mode": await self.purchase_mode(npub),
            }
        if name is not None:
            for member in members:
                if member.get("status") == "banned":
                    continue
                for svc in member.get("services") or []:
                    if svc.get("name") == name:
                        member_npub = member.get("npub", "")
                        return {
                            "npub": member_npub,
                            "url": svc.get("url", ""),
                            "name": name,
                            "role": member.get("role", ""),
                            "purchase_mode": await self.purchase_mode(member_npub),
                        }
            return None
        return None

    def invalidate_cache(self) -> None:
        self._json_cache.clear()
        self._text_cache.clear()
        self._retry_after.clear()

    async def close(self) -> None:
        await self._client.aclose()
