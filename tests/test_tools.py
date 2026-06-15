from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
    server_module._probe_cache.clear()
    yield
    server_module._settings = None
    server_module._registry = None
    server_module._challenges.clear()
    server_module._probe_cache.clear()


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
async def test_get_tax_rate_quotes_no_number():
    """The docent explains the model and redirects — it must not fabricate
    a network-wide rate or minimum."""
    result = await server_module.get_tax_rate()
    assert "rate_percent" not in result
    assert "min_sats" not in result
    assert "ad valorem" in result["model"]
    # Redirects the visitor to the Authority's own live source.
    assert "check_price" in result["how_to_get_the_live_rate"]
    assert "cascade" in result
    # No bare integer rate hiding anywhere in the values.
    assert not any(isinstance(v, (int, float)) for v in result.values())


@pytest.mark.asyncio
async def test_economic_model_is_qualitative():
    """No fabricated topology, fee percentages, or revenue figures — only a
    qualitative model plus pointers to the live sources."""
    result = await server_module.economic_model()
    assert isinstance(result, dict)

    # The old hardcoded numeric structure is gone.
    assert "topology" not in result
    assert "fees" not in result
    assert "cascade_effect" not in result
    assert "weekly_projections" not in result

    # Qualitative explanation remains.
    assert "ad valorem" in result["model"]
    assert isinstance(result["how_value_flows"], list)
    assert any("First Curator" in step for step in result["how_value_flows"])

    # Points at the live sources rather than quoting figures.
    where = result["where_the_numbers_live"]
    assert "check_price" in where["rates"]
    assert "list_services" in where["roster_and_topology"]

    # The diagram is kept but explicitly flagged as illustrative, not live.
    assert "illustrative_diagram_url" in result
    assert "dpyc-network-5auth-economics.svg" in result["illustrative_diagram_url"]
    assert "Illustrative" in result["diagram_note"]

    # No bare numeric values masquerading as live data.
    assert not any(isinstance(v, (int, float)) for v in result.values())


MEMBERS_WITH_SERVICES = [
    {
        "npub": ALICE_NPUB,
        "role": "operator",
        "status": "active",
        "display_name": "Alice",
        "services": [
            {
                "name": "alice-mcp",
                "url": "https://alice.example/mcp",
                "description": "Alice's data service",
            }
        ],
    },
    {
        "npub": CURATOR_NPUB,
        "role": "prime_authority",
        "status": "active",
        "display_name": "The Curator",
        "services": [
            {"name": "tollbooth-authority", "url": "https://curator.example/mcp"}
        ],
    },
    {
        "npub": BANNED_NPUB,
        "role": "operator",
        "status": "banned",
        "display_name": "Bad Actor",
        "services": [{"name": "bad", "url": "https://bad.example/mcp"}],
    },
]


@pytest.mark.asyncio
async def test_list_services_registry_only(mock_registry):
    mock_registry.get_members.return_value = MEMBERS_WITH_SERVICES
    result = await server_module.list_services(probe=False)
    assert result["success"] is True
    assert result["probed"] is False
    # Banned member excluded; two live services remain.
    names = {s["service_name"] for s in result["services"]}
    assert names == {"alice-mcp", "tollbooth-authority"}
    # No probe → no live block, and registry description is surfaced.
    assert all("live" not in s for s in result["services"])
    alice = next(s for s in result["services"] if s["service_name"] == "alice-mcp")
    assert alice["registry_description"] == "Alice's data service"


@pytest.mark.asyncio
async def test_list_services_kind_filter(mock_registry):
    mock_registry.get_members.return_value = MEMBERS_WITH_SERVICES
    result = await server_module.list_services(probe=False, kind="authority")
    assert result["count"] == 1
    assert result["services"][0]["role"] == "prime_authority"


@pytest.mark.asyncio
async def test_list_services_unknown_kind(mock_registry):
    result = await server_module.list_services(probe=False, kind="bogus")
    assert result["success"] is False
    assert "Unknown kind" in result["error"]


@pytest.mark.asyncio
async def test_list_services_probe_enriches(mock_registry):
    mock_registry.get_members.return_value = MEMBERS_WITH_SERVICES

    async def fake_probe(url):
        return {"probe_status": "live", "server_name": url, "tool_count": 3}

    with patch.object(server_module, "_probe_service", side_effect=fake_probe):
        result = await server_module.list_services(probe=True)

    assert result["probed"] is True
    assert all(s["live"]["probe_status"] == "live" for s in result["services"])


@pytest.mark.asyncio
async def test_list_services_sleeping_service_does_not_break(mock_registry):
    mock_registry.get_members.return_value = MEMBERS_WITH_SERVICES

    async def sleepy_probe(url):
        return {"probe_status": "timeout", "note": "warming up"}

    with patch.object(server_module, "_probe_service", side_effect=sleepy_probe):
        result = await server_module.list_services(probe=True)

    assert result["success"] is True
    assert all(s["live"]["probe_status"] == "timeout" for s in result["services"])


@pytest.mark.asyncio
async def test_probe_service_is_defensive():
    """A failed handshake must resolve to a structured status, never raise."""

    class BoomClient:
        def __init__(self, url):
            pass

        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, *a):
            return False

    with patch.object(server_module, "Client", BoomClient):
        result = await server_module._probe_service("https://nope.example/mcp")
    assert result["probe_status"] == "unreachable"


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
    assert "# About the DPYC Social Contract" in result
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


# ---------------------------------------------------------------------------
# _commit_advocate — lookup cache update
# ---------------------------------------------------------------------------

SAMPLE_CACHE = {
    "$schema": "../schemas/members.schema.json",
    "version": "1.1.0",
    "updated_at": "2026-03-01T00:00:00Z",
    "members": [
        {
            "npub": CURATOR_NPUB,
            "role": "prime_authority",
            "status": "active",
            "display_name": "The Curator",
        },
    ],
}


def _make_settings_mock(github_token: str = "ghp_test123") -> MagicMock:
    """Create a mock OracleSettings."""
    s = MagicMock()
    s.github_token = github_token
    s.dpyc_community_repo = "lonniev/dpyc-community"
    return s


@pytest.mark.asyncio
async def test_commit_advocate_updates_lookup_cache():
    """_commit_advocate writes the individual file AND updates the cache."""
    import base64
    import json

    _, new_npub = _generate_test_keys()
    settings = _make_settings_mock()

    registry = AsyncMock(spec=CommunityRegistry)
    registry.get_first_curator = AsyncMock(
        return_value={"npub": CURATOR_NPUB}
    )

    cache_b64 = base64.b64encode(
        json.dumps(SAMPLE_CACHE).encode()
    ).decode()

    # Build response mocks for the three HTTP calls.
    # httpx Response.json() and .raise_for_status() are sync, so use
    # MagicMock (not AsyncMock) for the response objects.

    # 1. PUT individual file
    put_file_resp = MagicMock()
    put_file_resp.raise_for_status = MagicMock()
    put_file_resp.json.return_value = {
        "content": {
            "html_url": (
                f"https://github.com/lonniev/dpyc-community/"
                f"blob/main/members/advocates/{new_npub}.json"
            )
        }
    }

    # 2. GET cache file (returns current content + sha)
    get_cache_resp = MagicMock()
    get_cache_resp.raise_for_status = MagicMock()
    get_cache_resp.json.return_value = {
        "sha": "abc123",
        "content": cache_b64,
    }

    # 3. PUT cache file
    put_cache_resp = MagicMock()
    put_cache_resp.raise_for_status = MagicMock()
    put_cache_resp.json.return_value = {"content": {"html_url": "..."}}

    # Sequence the httpx calls: PUT (file), GET (cache), PUT (cache)
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(side_effect=[put_file_resp, put_cache_resp])
    mock_client.get = AsyncMock(return_value=get_cache_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("dpyc_oracle.server.httpx.AsyncClient", return_value=mock_client):
        url = await server_module._commit_advocate(
            settings,
            registry,
            new_npub,
            "Test Advocate",
            [{"name": "test-svc", "url": "https://test.example.com"}],
        )

    assert "members/advocates/" in url

    # Verify the cache PUT was called with the new member appended
    assert mock_client.put.call_count == 2
    cache_put_call = mock_client.put.call_args_list[1]
    cache_body = cache_put_call.kwargs["json"]
    assert cache_body["sha"] == "abc123"
    assert "[Advocate] Update lookup cache" in cache_body["message"]

    # Decode the written cache content and verify the new member is present
    written_bytes = base64.b64decode(cache_body["content"])
    written_cache = json.loads(written_bytes)
    npubs_in_cache = [m["npub"] for m in written_cache["members"]]
    assert new_npub in npubs_in_cache
    assert CURATOR_NPUB in npubs_in_cache
    assert len(written_cache["members"]) == 2

    # Registry cache should be invalidated
    registry.invalidate_cache.assert_called_once()


@pytest.mark.asyncio
async def test_commit_advocate_cache_update_failure_is_non_fatal():
    """If cache update fails, _commit_advocate still returns success."""
    _, new_npub = _generate_test_keys()
    settings = _make_settings_mock()

    registry = AsyncMock(spec=CommunityRegistry)
    registry.get_first_curator = AsyncMock(
        return_value={"npub": CURATOR_NPUB}
    )

    # PUT individual file succeeds (sync .json() like real httpx)
    put_file_resp = MagicMock()
    put_file_resp.raise_for_status = MagicMock()
    put_file_resp.json.return_value = {
        "content": {
            "html_url": (
                f"https://github.com/lonniev/dpyc-community/"
                f"blob/main/members/advocates/{new_npub}.json"
            )
        }
    }

    # GET cache fails with an HTTP error
    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=put_file_resp)
    mock_client.get = AsyncMock(side_effect=Exception("Network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("dpyc_oracle.server.httpx.AsyncClient", return_value=mock_client):
        url = await server_module._commit_advocate(
            settings,
            registry,
            new_npub,
            "Test Advocate",
            [{"name": "test-svc", "url": "https://test.example.com"}],
        )

    # Individual file URL is still returned
    assert "members/advocates/" in url

    # Only the individual file PUT was made (cache PUT was skipped)
    assert mock_client.put.call_count == 1

    # Registry cache is still invalidated
    registry.invalidate_cache.assert_called_once()
