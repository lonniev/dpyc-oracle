from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from nostr_sdk import Keys, EventBuilder

import dpyc_oracle.server as server_module
from dpyc_oracle.registry import CommunityRegistry

ALICE_NPUB = "npub1xsll09qfnrkv6jazqu934n872nplcue276slenl0eayqhwp3jdesmaz7mh"
CURATOR_NPUB = "npub1t0dhxjmwrlqpgc576wjxyeczv4d2lu3z8582uk8s8m3rh9w06a7sdwszm8"
BANNED_NPUB = "npub165lcuua3ahzd4388xswem27ql4v5x5tjl9h52mstn4wua5m8a62s7mdze7"

SAMPLE_MEMBERS = {
    "members": [
        {
            "npub": ALICE_NPUB,
            "role": "operator",
            "status": "active",
            "display_name": "Alice",
            "services": [],
        },
        {
            "npub": CURATOR_NPUB,
            "role": "prime_authority",
            "status": "active",
            "display_name": "The Curator",
            "services": [],
        },
        {
            "npub": BANNED_NPUB,
            "role": "citizen",
            "status": "banned",
            "display_name": "Bad Actor",
            "ban_reason": "Community vote: spam",
            "services": [],
        },
    ]
}


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset server globals before each test."""
    server_module._settings = None
    server_module._registry = None
    server_module._challenges.clear()
    yield
    server_module._settings = None
    server_module._registry = None
    server_module._challenges.clear()


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
    result = await server_module.lookup_member(ALICE_NPUB)
    assert isinstance(result, dict)
    assert result["display_name"] == "Alice"


@pytest.mark.asyncio
async def test_lookup_member_not_found(mock_registry):
    result = await server_module.lookup_member("npub1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqsclr0y")
    assert isinstance(result, str)
    assert "No member found" in result


@pytest.mark.asyncio
async def test_get_tax_rate():
    result = await server_module.get_tax_rate()
    assert result["rate_percent"] == 2
    assert result["min_sats"] == 10
    assert "note" in result


@pytest.mark.asyncio
async def test_economic_model():
    result = await server_module.economic_model()
    assert isinstance(result, dict)

    # Diagram URL
    assert "diagram_url" in result
    assert "dpyc-network-5auth-economics.svg" in result["diagram_url"]
    assert result["diagram_url"].startswith("https://raw.githubusercontent.com/")

    # Topology
    topo = result["topology"]
    assert topo["authorities"] == 5
    assert topo["operators"] == 30
    assert "chains" in topo
    assert "C_to_B_to_A" in topo["chains"]
    assert topo["chains"]["C_to_B_to_A"]["hops"] == 3

    # Fees
    fees = result["fees"]
    assert fees["certification_fee_percent"] == 2
    assert "curator_royalty_percent" not in fees

    # Cascade effect
    cascade = result["cascade_effect"]
    assert cascade["single_hop_effective_percent"] == 2.0
    assert cascade["three_hop_effective_percent"] == 2.0408
    assert cascade["cascade_overhead_at_max_depth_percent"] == 0.81

    # Weekly projections
    weekly = result["weekly_projections"]
    assert "ecosystem_revenue_usd" in weekly
    assert "curator_revenue_usd" in weekly
    assert weekly["assumptions"]["operators"] == 30
    assert weekly["assumptions"]["tool_calls_per_hour"] == 1000
    assert weekly["assumptions"]["avg_api_sats_per_call"] == 15


@pytest.mark.asyncio
async def test_get_rulebook(mock_registry):
    result = await server_module.get_rulebook()
    assert "# Governance" in result


@pytest.mark.asyncio
async def test_how_to_join():
    result = await server_module.how_to_join()
    assert "Citizen" in result
    assert "Advocate" in result
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
async def test_service_status():
    result = await server_module.service_status()
    assert result["service"] == "dpyc-oracle"
    versions = result["versions"]
    assert "dpyc_oracle" in versions
    assert "python" in versions
    assert "fastmcp" in versions
    assert "nostr_sdk" in versions


@pytest.mark.asyncio
async def test_stub_renounce_membership():
    result = await server_module.renounce_membership(ALICE_NPUB)
    assert result["status"] == "not_yet_implemented"


@pytest.mark.asyncio
async def test_stub_initiate_ban_election():
    result = await server_module.initiate_ban_election(ALICE_NPUB, "spam")
    assert result["status"] == "not_yet_implemented"


@pytest.mark.asyncio
async def test_stub_cast_ban_vote():
    result = await server_module.cast_ban_vote("election-1", "ban", ALICE_NPUB)
    assert result["status"] == "not_yet_implemented"


# ---------------------------------------------------------------------------
# request_citizenship
# ---------------------------------------------------------------------------


def _generate_test_keys():
    """Generate a throwaway Nostr keypair for testing."""
    keys = Keys.generate()
    return keys, keys.public_key().to_bech32()


@pytest.mark.asyncio
async def test_request_citizenship_success(mock_registry):
    _, npub = _generate_test_keys()
    result = await server_module.request_citizenship(npub, "Test User")
    assert result["success"] is True
    assert "challenge_id" in result
    assert "nonce" in result
    assert result["expires_in_seconds"] == 600
    assert "DPYC-CITIZENSHIP" in result["instructions"]


@pytest.mark.asyncio
async def test_request_citizenship_invalid_npub(mock_registry):
    result = await server_module.request_citizenship("not-an-npub", "Test")
    assert result["success"] is False
    assert "Invalid npub" in result["error"]


@pytest.mark.asyncio
async def test_request_citizenship_already_member(mock_registry):
    result = await server_module.request_citizenship(ALICE_NPUB, "Alice")
    assert result["success"] is False
    assert "Already a member" in result["error"]


@pytest.mark.asyncio
async def test_request_citizenship_duplicate_pending(mock_registry):
    _, npub = _generate_test_keys()
    result1 = await server_module.request_citizenship(npub, "User")
    assert result1["success"] is True

    result2 = await server_module.request_citizenship(npub, "User")
    assert result2["success"] is False
    assert "pending challenge" in result2["error"]


# ---------------------------------------------------------------------------
# confirm_citizenship
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_citizenship_invalid_challenge(mock_registry):
    _, npub = _generate_test_keys()
    result = await server_module.confirm_citizenship(npub, "bad-id", "{}")
    assert result["success"] is False
    assert "not found or expired" in result["error"]


@pytest.mark.asyncio
async def test_confirm_citizenship_npub_mismatch(mock_registry):
    keys, npub = _generate_test_keys()
    _, other_npub = _generate_test_keys()

    # Request challenge for npub
    req = await server_module.request_citizenship(npub, "User")
    assert req["success"] is True

    # Try to confirm with a different npub
    result = await server_module.confirm_citizenship(
        other_npub, req["challenge_id"], "{}"
    )
    assert result["success"] is False
    assert "does not match" in result["error"]


@pytest.mark.asyncio
async def test_confirm_citizenship_bad_event_json(mock_registry):
    _, npub = _generate_test_keys()
    req = await server_module.request_citizenship(npub, "User")
    assert req["success"] is True

    result = await server_module.confirm_citizenship(
        npub, req["challenge_id"], "not valid json"
    )
    assert result["success"] is False
    assert "Failed to parse" in result["error"]


@pytest.mark.asyncio
async def test_confirm_citizenship_wrong_signer(mock_registry):
    keys_a, npub_a = _generate_test_keys()
    keys_b, _ = _generate_test_keys()

    req = await server_module.request_citizenship(npub_a, "User A")
    assert req["success"] is True

    # Sign with keys_b but claim npub_a
    nonce = req["nonce"]
    event = EventBuilder.text_note(f"DPYC-CITIZENSHIP:{nonce}").sign_with_keys(keys_b)

    result = await server_module.confirm_citizenship(
        npub_a, req["challenge_id"], event.as_json()
    )
    assert result["success"] is False
    assert "does not match" in result["error"]


@pytest.mark.asyncio
async def test_confirm_citizenship_wrong_nonce(mock_registry):
    keys, npub = _generate_test_keys()
    req = await server_module.request_citizenship(npub, "User")
    assert req["success"] is True

    # Sign with correct keys but wrong nonce
    event = EventBuilder.text_note("DPYC-CITIZENSHIP:wrongnonce").sign_with_keys(keys)

    result = await server_module.confirm_citizenship(
        npub, req["challenge_id"], event.as_json()
    )
    assert result["success"] is False
    assert "must contain" in result["error"]


@pytest.mark.asyncio
async def test_confirm_citizenship_expired_challenge(mock_registry):
    keys, npub = _generate_test_keys()
    req = await server_module.request_citizenship(npub, "User")
    assert req["success"] is True

    # Manually expire the challenge
    server_module._challenges[req["challenge_id"]]["expires_at"] = 0

    event = EventBuilder.text_note(
        f"DPYC-CITIZENSHIP:{req['nonce']}"
    ).sign_with_keys(keys)

    result = await server_module.confirm_citizenship(
        npub, req["challenge_id"], event.as_json()
    )
    assert result["success"] is False
    assert "not found or expired" in result["error"]


@pytest.mark.asyncio
async def test_confirm_citizenship_full_success(mock_registry):
    """E2E: generate keypair → request → sign → confirm → PR created."""
    keys, npub = _generate_test_keys()

    req = await server_module.request_citizenship(npub, "New Citizen")
    assert req["success"] is True

    # Sign the challenge with the correct keys
    nonce = req["nonce"]
    event = EventBuilder.text_note(f"DPYC-CITIZENSHIP:{nonce}").sign_with_keys(keys)

    # Mock _commit_membership since we don't have a real GitHub token
    with patch.object(
        server_module,
        "_commit_membership",
        new_callable=AsyncMock,
        return_value=f"https://github.com/lonniev/dpyc-community/blob/main/members/citizens/{npub}.json",
    ) as mock_commit:
        result = await server_module.confirm_citizenship(
            npub, req["challenge_id"], event.as_json()
        )

    assert result["success"] is True
    assert result["status"] == "admitted"
    assert "members/citizens/" in result["commit_url"]
    assert "Welcome" in result["message"]

    # Challenge should be consumed
    assert req["challenge_id"] not in server_module._challenges

    # Commit helper was called with correct args
    mock_commit.assert_called_once()
    call_args = mock_commit.call_args
    assert call_args[0][2] == npub  # npub arg
    assert call_args[0][3] == "New Citizen"  # display_name arg


# ---------------------------------------------------------------------------
# check_ban_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_ban_status_active_member(mock_registry):
    result = await server_module.check_ban_status(ALICE_NPUB)
    assert result["banned"] is False
    assert result["reason"] is None


@pytest.mark.asyncio
async def test_check_ban_status_banned_member(mock_registry):
    result = await server_module.check_ban_status(BANNED_NPUB)
    assert result["banned"] is True
    assert "spam" in result["reason"]


@pytest.mark.asyncio
async def test_check_ban_status_unknown_npub(mock_registry):
    """Unknown npub is not banned — they're just not a member."""
    keys = Keys.generate()
    unknown_npub = keys.public_key().to_bech32()
    result = await server_module.check_ban_status(unknown_npub)
    assert result["banned"] is False


@pytest.mark.asyncio
async def test_check_ban_status_invalid_npub(mock_registry):
    result = await server_module.check_ban_status("not-an-npub")
    assert result["banned"] is False
    assert "Invalid npub" in result.get("error", "")


@pytest.mark.asyncio
async def test_confirm_citizenship_pr_failure_returns_error(mock_registry):
    """If PR creation fails, the error is surfaced but challenge is NOT consumed."""
    keys, npub = _generate_test_keys()

    req = await server_module.request_citizenship(npub, "User")
    assert req["success"] is True

    nonce = req["nonce"]
    event = EventBuilder.text_note(f"DPYC-CITIZENSHIP:{nonce}").sign_with_keys(keys)

    with patch.object(
        server_module,
        "_commit_membership",
        new_callable=AsyncMock,
        side_effect=RuntimeError("GitHub token not configured"),
    ):
        result = await server_module.confirm_citizenship(
            npub, req["challenge_id"], event.as_json()
        )

    assert result["success"] is False
    assert "membership commit failed" in result["error"]


# ---------------------------------------------------------------------------
# register_authority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_authority_success(mock_registry):
    """New authority with valid upstream is committed to the registry."""
    _, new_npub = _generate_test_keys()

    with patch.object(
        server_module,
        "_commit_authority",
        new_callable=AsyncMock,
        return_value=f"https://github.com/lonniev/dpyc-community/blob/main/members/authorities/{new_npub}.json",
    ) as mock_commit:
        result = await server_module.register_authority(
            authority_npub=new_npub,
            display_name="New Authority",
            service_url="https://new-authority.example.com/mcp",
            upstream_authority_npub=CURATOR_NPUB,
        )

    assert result["success"] is True
    assert result["status"] == "registered"
    assert "members/authorities/" in result["commit_url"]
    assert "New Authority" in result["message"]
    mock_commit.assert_called_once()


@pytest.mark.asyncio
async def test_register_authority_invalid_npub(mock_registry):
    result = await server_module.register_authority(
        authority_npub="not-an-npub",
        display_name="Bad",
        service_url="https://example.com",
        upstream_authority_npub=CURATOR_NPUB,
    )
    assert result["success"] is False
    assert "Invalid authority_npub" in result["error"]


@pytest.mark.asyncio
async def test_register_authority_invalid_upstream_npub(mock_registry):
    _, new_npub = _generate_test_keys()
    result = await server_module.register_authority(
        authority_npub=new_npub,
        display_name="New",
        service_url="https://example.com",
        upstream_authority_npub="not-an-npub",
    )
    assert result["success"] is False
    assert "Invalid upstream_authority_npub" in result["error"]


@pytest.mark.asyncio
async def test_register_authority_upstream_not_found(mock_registry):
    _, new_npub = _generate_test_keys()
    _, unknown_upstream = _generate_test_keys()
    result = await server_module.register_authority(
        authority_npub=new_npub,
        display_name="New",
        service_url="https://example.com",
        upstream_authority_npub=unknown_upstream,
    )
    assert result["success"] is False
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_register_authority_upstream_wrong_role(mock_registry):
    """Upstream must be authority or prime_authority, not citizen/operator."""
    _, new_npub = _generate_test_keys()
    result = await server_module.register_authority(
        authority_npub=new_npub,
        display_name="New",
        service_url="https://example.com",
        upstream_authority_npub=ALICE_NPUB,  # Alice is an operator
    )
    assert result["success"] is False
    assert "not 'authority'" in result["error"]


@pytest.mark.asyncio
async def test_register_authority_already_registered(mock_registry):
    result = await server_module.register_authority(
        authority_npub=ALICE_NPUB,  # Already registered as operator
        display_name="Alice",
        service_url="https://example.com",
        upstream_authority_npub=CURATOR_NPUB,
    )
    assert result["success"] is False
    assert "already registered" in result["error"]


@pytest.mark.asyncio
async def test_register_authority_commit_failure(mock_registry):
    _, new_npub = _generate_test_keys()

    with patch.object(
        server_module,
        "_commit_authority",
        new_callable=AsyncMock,
        side_effect=RuntimeError("GitHub token not configured"),
    ):
        result = await server_module.register_authority(
            authority_npub=new_npub,
            display_name="New",
            service_url="https://example.com",
            upstream_authority_npub=CURATOR_NPUB,
        )

    assert result["success"] is False
    assert "commit failed" in result["error"]


# ---------------------------------------------------------------------------
# register_advocate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_advocate_success(mock_registry):
    """New advocate with valid service info is committed to the registry."""
    _, new_npub = _generate_test_keys()

    with patch.object(
        server_module,
        "_commit_advocate",
        new_callable=AsyncMock,
        return_value=f"https://github.com/lonniev/dpyc-community/blob/main/members/advocates/{new_npub}.json",
    ) as mock_commit:
        result = await server_module.register_advocate(
            npub=new_npub,
            display_name="OAuth2 Collector",
            service_name="tollbooth-oauth2-collector",
            service_url="https://tollbooth-oauth2-collector.fastmcp.app",
            service_description="Community OAuth2 callback mailbox",
        )

    assert result["success"] is True
    assert result["status"] == "registered"
    assert "members/advocates/" in result["commit_url"]
    assert "OAuth2 Collector" in result["message"]
    assert "tollbooth-oauth2-collector" in result["message"]
    mock_commit.assert_called_once()


@pytest.mark.asyncio
async def test_register_advocate_invalid_npub(mock_registry):
    result = await server_module.register_advocate(
        npub="not-an-npub",
        display_name="Bad",
        service_name="svc",
        service_url="https://example.com",
        service_description="desc",
    )
    assert result["success"] is False
    assert "Invalid npub" in result["error"]


@pytest.mark.asyncio
async def test_register_advocate_already_registered(mock_registry):
    result = await server_module.register_advocate(
        npub=ALICE_NPUB,  # Already registered as operator
        display_name="Alice",
        service_name="svc",
        service_url="https://example.com",
        service_description="desc",
    )
    assert result["success"] is False
    assert "already registered" in result["error"]


@pytest.mark.asyncio
async def test_register_advocate_commit_failure(mock_registry):
    _, new_npub = _generate_test_keys()

    with patch.object(
        server_module,
        "_commit_advocate",
        new_callable=AsyncMock,
        side_effect=RuntimeError("GitHub token not configured"),
    ):
        result = await server_module.register_advocate(
            npub=new_npub,
            display_name="Collector",
            service_name="svc",
            service_url="https://example.com",
            service_description="desc",
        )

    assert result["success"] is False
    assert "commit failed" in result["error"]
