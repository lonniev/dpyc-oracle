"""Registry writes for operators are made only by the Authority that signs them."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import dpyc_oracle.server as server_module

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
