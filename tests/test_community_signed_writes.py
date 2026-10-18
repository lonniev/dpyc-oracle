"""An Advocate registers itself, and a campaign is published by its author: each signs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import dpyc_oracle.server as server_module

ADVOCATE_NPUB = "npub1xsll09qfnrkv6jazqu934n872nplcue276slenl0eayqhwp3jdesmaz7mh"
AUTHOR_NPUB = "npub1t0dhxjmwrlqpgc576wjxyeczv4d2lu3z8582uk8s8m3rh9w06a7sdwszm8"
STRANGER_NPUB = "npub165lcuua3ahzd4388xswem27ql4v5x5tjl9h52mstn4wua5m8a62s7mdze7"

WRITES = [
    (server_module.register_advocate, ADVOCATE_NPUB, {
        "npub": ADVOCATE_NPUB, "display_name": "collector", "service_name": "collector",
        "service_url": "https://collector.example", "service_description": "callbacks",
    }),
    (server_module.publish_campaign, AUTHOR_NPUB, {
        "author_npub": AUTHOR_NPUB, "operator_npub": ADVOCATE_NPUB,
        "campaign_json": "not json",
    }),
]


async def _call(tool, args, signer):
    registry = MagicMock()
    registry.lookup_member = AsyncMock(return_value={"role": "citizen"})
    fn = getattr(tool, "fn", tool)
    with (
        patch.object(server_module, "signed_npub", return_value=signer),
        patch.object(server_module, "_ensure_initialized", return_value=(None, registry)),
    ):
        return await fn(**args)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "owner", "args"), WRITES)
@pytest.mark.parametrize("signer", [None, STRANGER_NPUB])
async def test_a_write_its_own_npub_did_not_sign_is_refused(tool, owner, args, signer):
    result = await _call(tool, args, signer)
    assert result["success"] is False
    assert "must be signed with its key" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "owner", "args"), WRITES)
async def test_a_write_its_own_npub_signed_passes_the_signature_gate(tool, owner, args):
    result = await _call(tool, args, owner)
    # The stubs stop each tool at its next check (already a member; bad JSON).
    assert result["success"] is False
    assert "must be signed with its key" not in result["error"]
