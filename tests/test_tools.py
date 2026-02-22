from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from nostr_sdk import Keys, EventBuilder

import dpyc_oracle.server as server_module
from dpyc_oracle.registry import CommunityRegistry

ALICE_NPUB = "npub1xsll09qfnrkv6jazqu934n872nplcue276slenl0eayqhwp3jdesmaz7mh"
CURATOR_NPUB = "npub1t0dhxjmwrlqpgc576wjxyeczv4d2lu3z8582uk8s8m3rh9w06a7sdwszm8"

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
    with pytest.raises(NotImplementedError, match="renounce_membership"):
        await server_module.renounce_membership(ALICE_NPUB)


@pytest.mark.asyncio
async def test_stub_initiate_ban_election():
    with pytest.raises(NotImplementedError, match="initiate_ban_election"):
        await server_module.initiate_ban_election(ALICE_NPUB, "spam")


@pytest.mark.asyncio
async def test_stub_cast_ban_vote():
    with pytest.raises(NotImplementedError, match="cast_ban_vote"):
        await server_module.cast_ban_vote("election-1", "ban", ALICE_NPUB)


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
        return_value="https://github.com/lonniev/dpyc-community/blob/main/members.json",
    ) as mock_commit:
        result = await server_module.confirm_citizenship(
            npub, req["challenge_id"], event.as_json()
        )

    assert result["success"] is True
    assert result["status"] == "admitted"
    assert "members.json" in result["commit_url"]
    assert "Welcome" in result["message"]

    # Challenge should be consumed
    assert req["challenge_id"] not in server_module._challenges

    # Commit helper was called with correct args
    mock_commit.assert_called_once()
    call_args = mock_commit.call_args
    assert call_args[0][2] == npub  # npub arg
    assert call_args[0][3] == "New Citizen"  # display_name arg


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
