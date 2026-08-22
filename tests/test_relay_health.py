"""Demotion of relays proven unreachable.

The bug these guard against: relays.json declared a dead relay primary, the
Oracle served it first to the whole fleet, and every Secure Courier pinned its
rendezvous to a relay that could not carry the reply.

The constraint they also guard: the read path must stay free. get_relays() is
on every operator's cold-start critical path.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from dpyc_oracle import relay_health

DECLARED = [
    "wss://relay.primal.net",
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]


def _alive(url: str) -> dict:
    return {"relay": url, "alive": True, "latency_ms": 40, "detail": "served 1 event(s)"}


def _dead(url: str) -> dict:
    return {"relay": url, "alive": False, "latency_ms": 900, "detail": "RelayStatus.TERMINATED"}


@pytest.fixture(autouse=True)
def _clear():
    relay_health._demotions.clear()
    yield
    relay_health._demotions.clear()


class TestOrdering:
    def test_untouched_when_nothing_is_demoted(self):
        """The common case. No reports means no opinion, so no reordering."""
        assert relay_health.order_by_health(DECLARED) == DECLARED

    def test_a_demoted_relay_moves_to_the_back(self):
        """The actual outage: primal declared first, proven dead."""
        relay_health.apply_probe(_dead("wss://relay.primal.net"))
        assert relay_health.order_by_health(DECLARED) == [
            "wss://relay.damus.io",
            "wss://nos.lol",
            "wss://relay.nostr.band",
            "wss://relay.primal.net",
        ]

    def test_nothing_is_ever_dropped(self):
        """A relay we cannot reach may still work from another network."""
        for url in DECLARED:
            relay_health.apply_probe(_dead(url))
        assert sorted(relay_health.order_by_health(DECLARED)) == sorted(DECLARED)

    def test_declared_order_survives_within_both_groups(self):
        relay_health.apply_probe(_dead("wss://relay.primal.net"))
        relay_health.apply_probe(_dead("wss://nos.lol"))
        assert relay_health.order_by_health(DECLARED) == [
            "wss://relay.damus.io",
            "wss://relay.nostr.band",
            "wss://relay.primal.net",
            "wss://nos.lol",
        ]

    def test_ranking_only_demotes_never_promotes(self):
        """A live probe clears a demotion; it must not jump the relay forward."""
        relay_health.apply_probe(_alive("wss://relay.nostr.band"))
        assert relay_health.order_by_health(DECLARED) == DECLARED


class TestRecovery:
    def test_a_live_probe_clears_an_existing_demotion(self):
        relay_health.apply_probe(_dead("wss://nos.lol"))
        assert "wss://nos.lol" in relay_health.demotions()
        relay_health.apply_probe(_alive("wss://nos.lol"))
        assert relay_health.demotions() == {}

    def test_a_demotion_expires_on_its_own(self):
        """The TTL is the decay function — recovery needs no success report."""
        relay_health.apply_probe(_dead("wss://nos.lol"))
        relay_health._demotions["wss://nos.lol"] = (
            _dead("wss://nos.lol"),
            time.monotonic() - relay_health.DEMOTION_TTL_SECONDS - 1,
        )
        assert relay_health.demotions() == {}
        assert relay_health.order_by_health(DECLARED) == DECLARED


class TestProbeRelay:
    @pytest.mark.asyncio
    async def test_probe_never_raises(self):
        """A probe reports; it does not fail. A raising probe would break bootstrap."""
        with patch.object(
            relay_health, "_attempt", AsyncMock(side_effect=OSError("connection refused")),
        ):
            result = await relay_health.probe_relay("wss://relay.example")
        assert result["alive"] is False
        assert "connection refused" in result["detail"]

    @pytest.mark.asyncio
    async def test_second_attempt_rescues_a_flaky_relay(self):
        """A relay that is up but unlucky on one connect must not be demoted."""
        attempt = AsyncMock(side_effect=[OSError("flake"), (True, "served 1 event(s)")])
        with patch.object(relay_health, "_attempt", attempt):
            result = await relay_health.probe_relay("wss://relay.example")
        assert result["alive"] is True
        assert attempt.await_count == 2

    def test_the_ordering_path_has_no_probe_in_it(self):
        """Structural guard: ordering is pure bookkeeping, never network I/O.

        If someone later reintroduces probing on the read path, this fails —
        the whole point is that a busy fleet never waits behind a survey.
        """
        with patch.object(
            relay_health, "probe_relay", AsyncMock(side_effect=AssertionError("probed!")),
        ), patch.object(
            relay_health, "_attempt", AsyncMock(side_effect=AssertionError("probed!")),
        ):
            assert relay_health.order_by_health(DECLARED) == DECLARED
            assert relay_health.demotions() == {}
