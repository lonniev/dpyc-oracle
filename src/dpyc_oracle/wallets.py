"""Which Lightning wallets a new guest should hear about first.

The list of wallets is ``dpyc-community/wallets.json``: a short catalog with
each wallet's installers and logo. What changes week to week is which of them
people are using, so the ranking is read live from Brave Search: each wallet
scores the number of results for the catalog's ``query`` that mention it by
name. The pinned wallet always leads; ties keep the catalog's order.

Brave returns web pages, not wallets, so a wallet missing from the catalog
can never appear. That is the point: every link a guest is shown was checked
by a person.

When there is no key, or Brave does not answer, the catalog's own order is the
answer. A guest looking for a wallet is never shown an error instead.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from tollbooth.web_search import BraveSearch, Hit, WebSearchError

logger = logging.getLogger(__name__)

_COUNT = 20

# The fields a page may show; anything else in the catalog stays here.
_SHOWN = ("id", "name", "line", "custody", "buys_in_app",
          "homepage", "app_store", "google_play", "logo", "pinned")

_cache: tuple[dict[str, Any], float] | None = None


def _names(wallet: dict[str, Any]) -> list[re.Pattern[str]]:
    words = [wallet.get("name", ""), *wallet.get("aliases", [])]
    return [re.compile(rf"(?<![\w-]){re.escape(w)}(?![\w-])", re.IGNORECASE)
            for w in words if isinstance(w, str) and w.strip()]


def rank(wallets: list[dict[str, Any]], results: list[Hit]) -> list[dict[str, Any]]:
    """The catalog's wallets, each with ``mentions``, in the order to show them.

    A result counts once for a wallet however often it names it, so one long
    review cannot outvote twenty short ones.
    """
    texts = [r.text for r in results]
    scored = []
    for order, w in enumerate(wallets):
        names = _names(w)
        mentions = sum(1 for t in texts if any(n.search(t) for n in names))
        scored.append((not w.get("pinned"), -mentions, order, {**w, "mentions": mentions}))
    scored.sort(key=lambda s: s[:3])
    return [s[3] for s in scored]


def _shown(wallet: dict[str, Any]) -> dict[str, Any]:
    out = {k: wallet[k] for k in _SHOWN if k in wallet}
    if "mentions" in wallet:
        out["mentions"] = wallet["mentions"]
    return out


async def _search(query: str, key: str) -> list[Hit] | None:
    """Brave's web results for ``query``, or None when it does not answer.

    The SDK's search names a failure by its status alone, so neither the key
    nor a response echoing it reaches a log.
    """
    try:
        return await BraveSearch(key).search(query, count=_COUNT)
    except WebSearchError as exc:
        logger.warning("Brave Search: %s; using the catalog order.", exc)
        return None


async def lightning_wallets(catalog: dict[str, Any], key: str | None, ttl: float) -> dict[str, Any]:
    """The wallets to show, ranked live when possible, cached for ``ttl``."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[1] < ttl:
        return _cache[0]

    wallets = [w for w in catalog.get("wallets", []) if isinstance(w, dict)]
    query = str(catalog.get("query") or "")
    show = int(catalog.get("show") or len(wallets))

    results = await _search(query, key) if key and query else None
    if results:
        ordered, by = rank(wallets, results), "brave"
    else:
        ordered = rank(wallets, [])
        for w in ordered:
            w.pop("mentions", None)
        by = "catalog"

    answer = {
        "success": True,
        "wallets": [_shown(w) for w in ordered[:show]],
        "ranked_by": by,
        "query": query,
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "credit": catalog.get("credit", ""),
    }
    # A catalog-order answer is cached briefly, so a Brave outage is retried
    # within the hour rather than tomorrow.
    _cache = (answer, now if by == "brave" else now - max(0.0, ttl - 3600))
    return answer


def clear_cache() -> None:
    global _cache
    _cache = None
