from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from dpyc_oracle.registry import CommunityRegistry, RegistryError

SAMPLE_MEMBERS = {
    "members": [
        {
            "npub": "npub1alice",
            "role": "operator",
            "status": "active",
            "display_name": "Alice",
            "services": [],
        },
        {
            "npub": "npub1curator",
            "role": "prime_authority",
            "status": "active",
            "display_name": "The Curator",
            "services": [],
        },
    ]
}

SAMPLE_GOVERNANCE = "# Governance\n\nRules go here."


@pytest.fixture
def registry():
    return CommunityRegistry(
        base_url="https://example.com/repo/main",
        cache_ttl_seconds=60,
    )


def _mock_response(json_data=None, text_data=None, status_code=200):
    resp = AsyncMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=Mock(), response=resp
        )
    if json_data is not None:
        resp.json.return_value = json_data
    if text_data is not None:
        resp.text = text_data
    return resp


@pytest.mark.asyncio
async def test_get_members_parses_wrapper(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        members = await registry.get_members()
    assert len(members) == 2
    assert members[0]["npub"] == "npub1alice"


@pytest.mark.asyncio
async def test_lookup_member_found(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        member = await registry.lookup_member("npub1alice")
    assert member is not None
    assert member["display_name"] == "Alice"


@pytest.mark.asyncio
async def test_lookup_member_not_found(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        member = await registry.lookup_member("npub1unknown")
    assert member is None


@pytest.mark.asyncio
async def test_get_first_curator(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        curator = await registry.get_first_curator()
    assert curator is not None
    assert curator["role"] == "prime_authority"
    assert curator["display_name"] == "The Curator"


@pytest.mark.asyncio
async def test_get_text_returns_markdown(registry):
    with patch.object(
        registry._client,
        "get",
        return_value=_mock_response(text_data=SAMPLE_GOVERNANCE),
    ):
        text = await registry.get_text("GOVERNANCE.md")
    assert "# Governance" in text


SAMPLE_NETWORK_STATUS = {
    "components": {
        "tollbooth-dpyc": {"current": "0.1.11", "minimum": "0.1.7"},
    },
    "protocols": ["dpyp-01-base-certificate"],
    "last_updated": "2026-02-21",
}


@pytest.mark.asyncio
async def test_get_network_status(registry):
    with patch.object(
        registry._client,
        "get",
        return_value=_mock_response(json_data=SAMPLE_NETWORK_STATUS),
    ):
        status = await registry.get_network_status()
    assert "components" in status
    assert status["components"]["tollbooth-dpyc"]["current"] == "0.1.11"
    assert "dpyp-01-base-certificate" in status["protocols"]


@pytest.mark.asyncio
async def test_cache_hit_within_ttl(registry):
    mock_get = AsyncMock(return_value=_mock_response(json_data=SAMPLE_MEMBERS))
    with patch.object(registry._client, "get", mock_get):
        await registry.get_members()
        await registry.get_members()
    assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_cache_expired_refetches(registry):
    registry._ttl = 0  # expire immediately
    mock_get = AsyncMock(return_value=_mock_response(json_data=SAMPLE_MEMBERS))
    with patch.object(registry._client, "get", mock_get):
        await registry.get_members()
        # Force cache to be stale by setting fetch time in the past
        for key in registry._json_cache:
            data, _ = registry._json_cache[key]
            registry._json_cache[key] = (data, time.monotonic() - 10)
        await registry.get_members()
    assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_http_error_raises_registry_error(registry):
    with patch.object(
        registry._client,
        "get",
        return_value=_mock_response(status_code=500),
    ):
        with pytest.raises(RegistryError, match="Failed to fetch"):
            await registry.get_members()


# --- Bootstrap-support resolvers ------------------------------------------

CHAIN_MEMBERS = {
    "members": [
        {
            "npub": "npub1prime",
            "role": "prime_authority",
            "status": "active",
            "display_name": "Prime",
            "services": [{"name": "dpyc-oracle", "url": "https://oracle/mcp"}],
        },
        {
            "npub": "npub1auth",
            "role": "authority",
            "status": "active",
            "display_name": "NorthAmerica",
            "upstream_authority_npub": "npub1prime",
            "services": [{"name": "authority", "url": "https://auth/mcp"}],
        },
        {
            "npub": "npub1op",
            "role": "operator",
            "status": "active",
            "display_name": "Excalibur",
            "upstream_authority_npub": "npub1auth",
            "services": [{"name": "excalibur", "url": "https://excalibur/mcp"}],
        },
    ]
}

SAMPLE_RELAYS = {
    "relays": [
        {"url": "wss://relay.primal.net", "primary": True},
        {"url": "wss://nos.lol"},
        "wss://relay.damus.io",
        {"url": "https://not-a-relay"},
    ]
}


@pytest.mark.asyncio
async def test_get_relays_primary_first_and_filtered(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_RELAYS)
    ):
        relays = await registry.get_relays()
    assert relays[0] == "wss://relay.primal.net"  # primary hoisted
    assert "wss://nos.lol" in relays and "wss://relay.damus.io" in relays
    assert all(r.startswith("wss://") for r in relays)  # http entry dropped


@pytest.mark.asyncio
async def test_resolve_authority_for_operator(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=CHAIN_MEMBERS)
    ):
        auth = await registry.resolve_authority_for("npub1op")
    assert auth == {"npub": "npub1auth", "url": "https://auth/mcp", "name": "authority"}


@pytest.mark.asyncio
async def test_resolve_authority_for_trust_root_is_none(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=CHAIN_MEMBERS)
    ):
        assert await registry.resolve_authority_for("npub1prime") is None


@pytest.mark.asyncio
async def test_purchase_mode_certified_vs_direct(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=CHAIN_MEMBERS)
    ):
        # operator under a non-Prime Authority pays up → certified
        assert await registry.purchase_mode("npub1op") == "certified"
        # Authority whose parent is Prime self-funds → direct
        assert await registry.purchase_mode("npub1auth") == "direct"
        # trust root → direct; unknown npub fails safe → direct
        assert await registry.purchase_mode("npub1prime") == "direct"
        assert await registry.purchase_mode("npub1ghost") == "direct"


@pytest.mark.asyncio
async def test_resolve_service_by_name_and_npub(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=CHAIN_MEMBERS)
    ):
        by_name = await registry.resolve_service(name="excalibur")
        by_npub = await registry.resolve_service(npub="npub1op")
    assert by_name["url"] == "https://excalibur/mcp"
    assert by_name["role"] == "operator"
    assert by_name["purchase_mode"] == "certified"
    assert by_npub["name"] == "excalibur"
    assert await registry.resolve_service(name="ghost") is None


@pytest.mark.asyncio
async def test_stale_served_on_refresh_failure(registry):
    """A failed refresh serves the last-known-good copy instead of failing closed."""
    registry._ttl = 0  # force a refresh on every call
    ok = _mock_response(json_data=SAMPLE_MEMBERS)
    boom = _mock_response(status_code=500)
    with patch.object(registry._client, "get", AsyncMock(side_effect=[ok, boom])):
        first = await registry.get_members()  # populates cache
        second = await registry.get_members()  # refresh fails → serve stale
    assert first == second
    assert second[0]["npub"] == "npub1alice"


def _chain(**overrides):
    """Operator -> regional -> authority -> prime, with one member's fields changed."""
    members = {
        "op": {"role": "operator", "status": "active", "upstream_authority_npub": "regional"},
        "regional": {"role": "authority", "status": "active", "upstream_authority_npub": "auth"},
        "auth": {"role": "authority", "status": "active", "upstream_authority_npub": "prime"},
        "prime": {"role": "prime_authority", "status": "active", "upstream_authority_npub": None},
    }
    for npub, fields in overrides.items():
        members.setdefault(npub, {}).update(fields)
    return {
        "members": [
            {"npub": npub, "services": [{"name": npub, "url": f"https://{npub}/mcp"}], **m}
            for npub, m in members.items()
        ]
    }


async def _resolve(registry, data, npub="op"):
    with patch.object(registry._client, "get", return_value=_mock_response(json_data=data)):
        return await registry.resolve_authority_for(npub)


@pytest.mark.asyncio
async def test_an_authority_chained_to_prime_is_named(registry):
    assert (await _resolve(registry, _chain()))["npub"] == "regional"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"regional": {"status": "banned"}},
        {"auth": {"status": "banned"}},
        {"regional": {"status": "inactive"}},
        {"op": {"status": "banned"}},
        {"regional": {"role": "operator"}},
        {"regional": {"upstream_authority_npub": "stranger"}},
        {"regional": {"upstream_authority_npub": None}},
        {"auth": {"upstream_authority_npub": "regional"}},
        {"op": {"upstream_authority_npub": "stranger"}},
    ],
    ids=[
        "banned-authority", "banned-grandparent", "inactive-authority", "banned-operator",
        "parent-not-an-authority", "chain-leaves-the-registry", "rogue-self-rooted",
        "chain-loops", "unlisted-authority",
    ],
)
async def test_no_authority_is_named_unless_the_chain_is_legitimate(registry, overrides):
    assert await _resolve(registry, _chain(**overrides)) is None


@pytest.mark.asyncio
async def test_prime_may_be_the_named_authority(registry):
    data = _chain(op={"upstream_authority_npub": "prime"})
    assert (await _resolve(registry, data))["npub"] == "prime"
