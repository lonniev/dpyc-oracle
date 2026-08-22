"""Demotion of relays that have been reported, and proven, unreachable.

``relays.json`` is a **guess** — a curated, human-ordered set. It is a good
guess, but it cannot know which relay is up right now, and a stale guess is
harmful: the Oracle's order reaches the whole fleet, every operator pins its
Secure Courier rendezvous to the first entry, and a rendezvous pinned to a
dead relay fails as "the patron never replied".

So the guess is tailored by **negative feedback only**.

- ``get_relays()`` never probes. It is on every operator's cold-start path,
  and a busy, happy fleet must not wait behind a survey it did not ask for.
  It serves the declared order with known-dead relays moved to the back.
- A probe happens only when someone reports a failure, and only against the
  relay they reported. One report, one probe.
- Success is never reported. It is far too frequent to be worth carrying, and
  a relay that works needs no announcement.

Two further properties fall out of that shape:

**Ranking only ever demotes.** A probe that finds a relay alive does not
promote it above its declared position; it just clears any demotion. The
declared order stays the expression of judgement about the set, and
measurement only ever says "not this one, not now".

**Recovery needs no success reports.** A demotion carries a TTL, so it decays
on its own. A relay that is genuinely down keeps getting reported and keeps
being re-demoted; a relay that recovered simply ages back into its declared
slot and gets another chance. The TTL *is* the decay function.

Demotions live in memory and are lost when this service recycles. That is
acceptable precisely because rank is derived rather than accumulated: losing
them costs one more report round, not knowledge that cannot be rebuilt.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from nostr_sdk import Client, Filter, Kind, RelayStatus, RelayUrl

logger = logging.getLogger(__name__)

# How long a proven-dead relay stays demoted before it is given another
# chance. This is the recovery mechanism — see the module docstring.
DEMOTION_TTL_SECONDS = 300

# Per-attempt budget. Two attempts, because a flaky-but-usable relay should
# not be demoted on one unlucky connect.
_ATTEMPT_TIMEOUT_SECONDS = 1.0
_ATTEMPTS = 2

# url -> (probe_result, demoted_at_monotonic). Only unreachable relays are
# recorded; a healthy probe removes the entry rather than adding one.
_demotions: dict[str, tuple[dict, float]] = {}


async def _attempt(url: str) -> tuple[bool, str]:
    """One connect + REQ→EOSE round trip. Raises on transport failure."""
    client = Client()
    try:
        relay_url = RelayUrl.parse(url)
        await client.add_relay(relay_url)
        await client.try_connect(timedelta(seconds=_ATTEMPT_TIMEOUT_SECONDS))
        relay = await client.relay(relay_url)
        if relay.status() != RelayStatus.CONNECTED:
            return False, str(relay.status())
        # Accepting a socket is not the same as serving. Ask for one event so
        # the probe proves the relay actually answers queries.
        events = await relay.fetch_events(
            Filter().kind(Kind(1)).limit(1),
            timedelta(seconds=_ATTEMPT_TIMEOUT_SECONDS),
        )
        return True, f"served {len(events)} event(s)"
    finally:
        try:
            await client.shutdown()
        except Exception:  # noqa: BLE001 — teardown must never mask a result
            pass


async def probe_relay(url: str) -> dict:
    """Measure one relay. Never raises — a probe reports, it does not fail."""
    started = time.monotonic()
    detail = "not attempted"
    for _ in range(_ATTEMPTS):
        try:
            alive, detail = await _attempt(url)
            if alive:
                return {
                    "relay": url,
                    "alive": True,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "detail": detail,
                }
        except Exception as exc:  # noqa: BLE001 — every failure is a datum
            detail = f"{type(exc).__name__}: {exc}"
    return {
        "relay": url,
        "alive": False,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "detail": detail,
    }


def _is_current(demoted_at: float) -> bool:
    return (time.monotonic() - demoted_at) < DEMOTION_TTL_SECONDS


def apply_probe(result: dict) -> bool:
    """Record a probe result. Returns True if the relay is now demoted.

    A dead relay is demoted; a live one has any existing demotion cleared.
    Nothing here promotes a relay above its declared position.
    """
    url = result["relay"]
    if result["alive"]:
        _demotions.pop(url, None)
        return False
    _demotions[url] = (result, time.monotonic())
    return True


def demotions() -> dict[str, dict]:
    """Currently-demoted relays, expired entries dropped as we go."""
    for url, (_, demoted_at) in list(_demotions.items()):
        if not _is_current(demoted_at):
            logger.info("Demotion of %s expired; it returns to declared rank", url)
            del _demotions[url]
    return {url: result for url, (result, _) in _demotions.items()}


def order_by_health(declared: list[str]) -> list[str]:
    """Return the declared order with known-dead relays moved to the back.

    Declared order is preserved within both groups, and nothing is ever
    dropped: a relay the Oracle could not reach may still be reachable from
    an operator on a different network, so a demotion is a last-resort
    ranking, not a removal.
    """
    demoted = demotions()
    keep = [url for url in declared if url not in demoted]
    push = [url for url in declared if url in demoted]
    return keep + push
