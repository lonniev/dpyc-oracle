"""Registry writes for operators are made only by the Authority that signs them."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Keys

import dpyc_oracle.server as server_module
from dpyc_oracle.registry import CommunityRegistry

AUTHORITY_NPUB = "npub1t0dhxjmwrlqpgc576wjxyeczv4d2lu3z8582uk8s8m3rh9w06a7sdwszm8"
OPERATOR_NPUB = "npub1xsll09qfnrkv6jazqu934n872nplcue276slenl0eayqhwp3jdesmaz7mh"
STRANGER_NPUB = "npub165lcuua3ahzd4388xswem27ql4v5x5tjl9h52mstn4wua5m8a62s7mdze7"

WRITES = [
    (server_module.register_operator, {
        "operator_npub": OPERATOR_NPUB, "display_name": "op",
        "service_url": "https://op.example/mcp", "authority_npub": AUTHORITY_NPUB,
    }),
    (server_module.update_operator, {
        "operator_npub": OPERATOR_NPUB, "authority_npub": AUTHORITY_NPUB,
        "display_name": "renamed",
    }),
    (server_module.deregister_operator, {
        "operator_npub": OPERATOR_NPUB, "authority_npub": AUTHORITY_NPUB,
    }),
]


def _registry() -> MagicMock:
    registry = MagicMock()
    registry.lookup_member = AsyncMock(return_value=None)
    registry.is_legitimate_authority_under = AsyncMock(return_value=False)
    return registry


async def _call(tool, args, signer):
    fn = getattr(tool, "fn", tool)
    with (
        patch.object(server_module, "signed_npub", return_value=signer),
        patch.object(server_module, "_ensure_initialized", return_value=(None, _registry())),
    ):
        return await fn(**args)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "args"), WRITES)
@pytest.mark.parametrize("signer", [None, STRANGER_NPUB])
async def test_a_write_the_authority_did_not_sign_is_refused(tool, args, signer):
    result = await _call(tool, args, signer)
    assert result["success"] is False
    assert "must be signed with its key" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "args"), WRITES)
async def test_a_write_the_authority_signed_passes_the_signature_gate(tool, args):
    result = await _call(tool, args, AUTHORITY_NPUB)
    # The registry stub knows no members, so the tool stops at its next check.
    assert "must be signed with its key" not in result.get("error", "")


REGISTER_AUTHORITY = {
    "authority_npub": OPERATOR_NPUB, "display_name": "new",
    "service_url": "https://new.example/mcp", "upstream_authority_npub": AUTHORITY_NPUB,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("signer", [None, STRANGER_NPUB, OPERATOR_NPUB])
async def test_a_new_authority_its_sponsor_did_not_sign_for_is_refused(signer):
    with patch.object(server_module, "_commit_authority", new_callable=AsyncMock) as commit:
        result = await _call(server_module.register_authority, REGISTER_AUTHORITY, signer)
    assert result["success"] is False
    assert "signed" in result["error"]
    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_new_authority_its_sponsor_signed_for_is_committed():
    registry = _registry()
    registry.lookup_member = AsyncMock(
        side_effect=lambda npub: {"role": "authority"} if npub == AUTHORITY_NPUB else None
    )
    with (
        patch.object(server_module, "signed_npub", return_value=AUTHORITY_NPUB),
        patch.object(server_module, "_ensure_initialized", return_value=(None, registry)),
        patch.object(server_module, "_commit_authority", AsyncMock(return_value="https://c")),
    ):
        fn = getattr(server_module.register_authority, "fn", server_module.register_authority)
        result = await fn(**REGISTER_AUTHORITY)
    assert result["success"] is True


SIBLING_NPUB = Keys.generate().public_key().to_bech32()
PRIME = {"npub": AUTHORITY_NPUB, "role": "prime_authority", "status": "active"}


def _authority(npub, upstream, status="active", role="authority"):
    return {"npub": npub, "role": role, "status": status, "upstream_authority_npub": upstream}


async def _register_signed_by_sibling(members):
    """Run the real registry rule over ``members``, with SIBLING_NPUB signing."""
    registry = CommunityRegistry.__new__(CommunityRegistry)
    registry.invalidate_cache = MagicMock()
    registry.get_members = AsyncMock(return_value=members)
    registry.lookup_member = AsyncMock(
        side_effect=lambda npub: next((m for m in members if m["npub"] == npub), None)
    )
    commit = AsyncMock(return_value="https://c")
    with (
        patch.object(server_module, "signed_npub", return_value=SIBLING_NPUB),
        patch.object(server_module, "_ensure_initialized", return_value=(None, registry)),
        patch.object(server_module, "_commit_authority", commit),
    ):
        fn = getattr(server_module.register_authority, "fn", server_module.register_authority)
        return await fn(**REGISTER_AUTHORITY), commit


@pytest.mark.asyncio
async def test_a_legitimate_child_of_the_sponsor_may_register_after_onboarding():
    result, commit = await _register_signed_by_sibling(
        [PRIME, _authority(SIBLING_NPUB, AUTHORITY_NPUB)]
    )
    assert result["success"] is True
    commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signer_entry",
    [
        pytest.param(_authority(SIBLING_NPUB, AUTHORITY_NPUB, status="banned"), id="banned"),
        pytest.param(_authority(SIBLING_NPUB, AUTHORITY_NPUB, status="inactive"), id="inactive"),
        pytest.param(_authority(SIBLING_NPUB, AUTHORITY_NPUB, role="operator"), id="operator"),
        pytest.param(_authority(SIBLING_NPUB, STRANGER_NPUB), id="other-parent"),
    ],
)
async def test_any_other_signer_cannot_register_under_the_sponsor(signer_entry):
    members = [PRIME, _authority(STRANGER_NPUB, AUTHORITY_NPUB), signer_entry]
    result, commit = await _register_signed_by_sibling(members)
    assert result["success"] is False
    assert "signed" in result["error"]
    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_signer_under_a_banned_sponsor_cannot_register():
    members = [{**PRIME, "status": "banned"}, _authority(SIBLING_NPUB, AUTHORITY_NPUB)]
    result, commit = await _register_signed_by_sibling(members)
    assert result["success"] is False
    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unreadable_registry_refuses_the_write():
    registry = _registry()
    registry.is_legitimate_authority_under = AsyncMock(side_effect=RuntimeError("down"))
    commit = AsyncMock()
    with (
        patch.object(server_module, "signed_npub", return_value=SIBLING_NPUB),
        patch.object(server_module, "_ensure_initialized", return_value=(None, registry)),
        patch.object(server_module, "_commit_authority", commit),
    ):
        fn = getattr(server_module.register_authority, "fn", server_module.register_authority)
        result = await fn(**REGISTER_AUTHORITY)
    assert result["success"] is False
    commit.assert_not_awaited()
