from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import dpyc_oracle.server as server_module
from dpyc_oracle.registry import CommunityRegistry

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


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset server globals before each test."""
    server_module._settings = None
    server_module._registry = None
    yield
    server_module._settings = None
    server_module._registry = None


SAMPLE_NETWORK_STATUS = {
    "components": {
        "tollbooth-dpyc": {"current": "0.1.11", "minimum": "0.1.7"},
        "tollbooth-authority": {"current": "0.1.1", "minimum": "0.1.0"},
    },
    "protocols": ["dpyp-01-base-certificate"],
    "last_updated": "2026-02-21",
    "advisory": "Test advisory summary.",
}


def _make_registry_mock():
    """Create a mock CommunityRegistry with standard responses."""
    mock = AsyncMock(spec=CommunityRegistry)
    mock.lookup_member = AsyncMock(side_effect=_lookup_member_side_effect)
    mock.get_first_curator = AsyncMock(
        return_value=SAMPLE_MEMBERS["members"][1]
    )
    mock.get_text = AsyncMock(side_effect=_get_text_side_effect)
    mock.get_members = AsyncMock(return_value=SAMPLE_MEMBERS["members"])
    mock.get_network_status = AsyncMock(return_value=SAMPLE_NETWORK_STATUS)
    return mock


async def _lookup_member_side_effect(npub: str):
    for m in SAMPLE_MEMBERS["members"]:
        if m["npub"] == npub:
            return m
    return None


async def _get_text_side_effect(path: str):
    if path == "README.md":
        return "# DPYC Community\n\nWelcome."
    if path == "GOVERNANCE.md":
        return "# Governance\n\nRules here."
    if path == "ADVISORY.md":
        return "# DPYC Network Advisory\n\nRedeploy for npub enforcement."
    return ""


@pytest.fixture
def mock_registry():
    mock = _make_registry_mock()
    with patch.object(server_module, "_ensure_initialized", return_value=(None, mock)):
        yield mock


@pytest.mark.asyncio
async def test_lookup_member_found(mock_registry):
    result = await server_module.lookup_member("npub1alice")
    assert isinstance(result, dict)
    assert result["display_name"] == "Alice"


@pytest.mark.asyncio
async def test_lookup_member_not_found(mock_registry):
    result = await server_module.lookup_member("npub1unknown")
    assert isinstance(result, str)
    assert "No member found" in result


@pytest.mark.asyncio
async def test_get_tax_rate():
    result = await server_module.get_tax_rate()
    assert result["rate_percent"] == 2
    assert result["min_sats"] == 10
    assert "note" in result


@pytest.mark.asyncio
async def test_get_rulebook(mock_registry):
    result = await server_module.get_rulebook()
    assert "# Governance" in result


@pytest.mark.asyncio
async def test_how_to_join():
    result = await server_module.how_to_join()
    assert "Citizen" in result
    assert "Operator" in result
    assert "Authority" in result
    assert "First Curator" in result
    assert "nak key generate" in result


@pytest.mark.asyncio
async def test_who_is_first_curator(mock_registry):
    result = await server_module.who_is_first_curator()
    assert isinstance(result, dict)
    assert result["role"] == "prime_authority"
    assert result["display_name"] == "The Curator"


@pytest.mark.asyncio
async def test_about(mock_registry):
    result = await server_module.about()
    assert "# About the DPYC Honor Chain" in result
    assert "# Governance" in result
    assert "DPYC Community" in result


@pytest.mark.asyncio
async def test_network_versions(mock_registry):
    result = await server_module.network_versions()
    assert isinstance(result, dict)
    assert "components" in result
    assert "tollbooth-dpyc" in result["components"]
    assert result["components"]["tollbooth-dpyc"]["current"] == "0.1.11"
    assert "protocols" in result
    assert "dpyp-01-base-certificate" in result["protocols"]
    assert result["last_updated"] == "2026-02-21"


@pytest.mark.asyncio
async def test_network_advisory(mock_registry):
    result = await server_module.network_advisory()
    assert isinstance(result, str)
    assert "# DPYC Network Advisory" in result
    assert "npub enforcement" in result


@pytest.mark.asyncio
async def test_stub_renounce_membership():
    with pytest.raises(NotImplementedError, match="renounce_membership"):
        await server_module.renounce_membership("npub1alice")


@pytest.mark.asyncio
async def test_stub_initiate_ban_election():
    with pytest.raises(NotImplementedError, match="initiate_ban_election"):
        await server_module.initiate_ban_election("npub1alice", "spam")


@pytest.mark.asyncio
async def test_stub_cast_ban_vote():
    with pytest.raises(NotImplementedError, match="cast_ban_vote"):
        await server_module.cast_ban_vote("election-1", "ban", "npub1alice")
