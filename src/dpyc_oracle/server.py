from __future__ import annotations

import logging

from fastmcp import FastMCP

from dpyc_oracle.config import OracleSettings
from dpyc_oracle.registry import CommunityRegistry

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
DPYC Oracle — community concierge for the DPYC Honor Chain.

DPYC ("Don't Pester Your Customer") is a philosophy and protocol for API \
monetization via Bitcoin Lightning micropayments. Users pre-fund a satoshi \
balance and consume API calls without KYC, stablecoins, or mid-session \
payment popups. Identity is a Nostr keypair (npub), not an email or \
username. Tollbooth monetizes complete business information at the MCP tool \
layer — not raw REST data fragments — using pre-funded Lightning balances \
that eliminate per-request payment ceremonies.

The Honor Chain is a voluntary community of Operators and Authorities who \
agree to transparent, auditable economic rules. Operators run MCP services \
and collect Lightning fares via Tollbooths. Authorities certify Operators \
and collect a small tax on every purchase order. The First Curator (Prime \
Authority) sits at the root of the chain and mints the initial cert-sat \
supply. Membership tiers: Citizen → Operator → Authority → First Curator.

This Oracle is a free, unauthenticated concierge that answers questions \
about membership, governance, onboarding, and tax rates by reading the \
dpyc-community registry on GitHub. It does not require payment or \
credentials.

Related repos:
- dpyc-community: https://github.com/lonniev/dpyc-community (registry + governance)
- tollbooth-dpyc: https://github.com/lonniev/tollbooth-dpyc (Python SDK for Tollbooth monetization)
- tollbooth-authority: https://github.com/lonniev/tollbooth-authority (Authority MCP service)
- thebrain-mcp: https://github.com/lonniev/thebrain-mcp (Personal Brain MCP service)
"""

_settings: OracleSettings | None = None
_registry: CommunityRegistry | None = None


def _ensure_initialized() -> tuple[OracleSettings, CommunityRegistry]:
    global _settings, _registry
    if _settings is None:
        _settings = OracleSettings()
    if _registry is None:
        _registry = CommunityRegistry(
            base_url=_settings.dpyc_community_base_url,
            cache_ttl_seconds=_settings.cache_ttl_seconds,
        )
    return _settings, _registry


mcp = FastMCP("dpyc-oracle", instructions=INSTRUCTIONS)


@mcp.tool()
async def about() -> str:
    """Extended narration about DPYC, the Honor Chain, and the Oracle.

    Fetches README.md and GOVERNANCE.md from the dpyc-community repo and
    assembles a comprehensive context answer.
    """
    _, registry = _ensure_initialized()
    readme = await registry.get_text("README.md")
    governance = await registry.get_text("GOVERNANCE.md")
    return (
        "# About the DPYC Honor Chain\n\n"
        f"{readme}\n\n"
        "---\n\n"
        "# Governance\n\n"
        f"{governance}"
    )


@mcp.tool()
async def lookup_member(npub: str) -> dict | str:
    """Look up a member by their Nostr npub.

    Returns the full member record if found, or a not-found message.
    """
    _, registry = _ensure_initialized()
    member = await registry.lookup_member(npub)
    if member is None:
        return f"No member found with npub: {npub}"
    return member


@mcp.tool()
async def get_tax_rate() -> dict:
    """Get the current Tollbooth tax rate.

    Returns the tax percentage that Authorities charge on certified
    purchase orders.
    """
    return {
        "rate_percent": 2,
        "min_sats": 10,
        "note": (
            "Tax per certification = max(10, ceil(amount_sats * 2 / 100)). "
            "Configurable per-Authority in a future release."
        ),
    }


@mcp.tool()
async def get_rulebook() -> str:
    """Fetch the DPYC Honor Chain governance document.

    Returns the raw markdown of GOVERNANCE.md from the dpyc-community repo.
    """
    _, registry = _ensure_initialized()
    return await registry.get_text("GOVERNANCE.md")


@mcp.tool()
async def how_to_join() -> str:
    """Tier-specific onboarding guide for joining the DPYC Honor Chain.

    Covers all four tiers: Citizen, Operator, Authority, and First Curator.
    Includes Nostr keygen instructions and practical next steps.
    """
    return """\
# How to Join the DPYC Honor Chain

## Step 1 — Generate a Nostr Identity

Every member needs a Nostr keypair. Your `npub` is your public identity.

```bash
# Option A: Use a Nostr client like Primal (https://primal.net)
# Create an account → your npub is shown in your profile

# Option B: CLI with nak (https://github.com/fiatjaf/nak)
nak key generate    # prints nsec (private) and npub (public)
```

**Keep your nsec private key safe.** You only share your npub.

## Step 2 — Choose Your Tier

### Citizen (Observer)
- No sponsorship required
- Read governance docs, follow community discussions
- To formalize: ask any Authority to sponsor your PR to members.json

### Operator (Run MCP Services)
- Find a sponsoring Authority willing to vouch for you
- The Authority submits a PR to `dpyc-community/members.json` adding your record
- Install `tollbooth-dpyc` in your MCP server for Lightning fare collection
- Configure your BTCPay Server instance for payment processing

### Authority (Certify Operators)
- Must already be an active Operator in good standing
- Requires sponsorship from an existing Authority or the First Curator
- Deploy `tollbooth-authority` to issue EdDSA-signed purchase certificates
- Fund your tax balance with the upstream Authority via Lightning

### First Curator (Prime Authority)
- There is exactly one First Curator at the root of the Honor Chain
- This role is not open for application — it is a governance position

## Step 3 — Get Sponsored

1. Introduce yourself in the community (GitHub Issues on dpyc-community)
2. An Authority reviews your intent and submits a PR with your member record
3. CI validates the record format; community reviews the PR
4. Once merged, you are an official member of the Honor Chain

## Useful Links

- Registry: https://github.com/lonniev/dpyc-community
- Tollbooth SDK: https://github.com/lonniev/tollbooth-dpyc
- Authority Service: https://github.com/lonniev/tollbooth-authority
- Primal (Nostr client): https://primal.net
- BTCPay Server: https://btcpayserver.org
"""


@mcp.tool()
async def who_is_first_curator() -> dict | str:
    """Identify the First Curator (Prime Authority) of the Honor Chain.

    Returns the curator's npub, display name, and member record.
    """
    _, registry = _ensure_initialized()
    curator = await registry.get_first_curator()
    if curator is None:
        return "No Prime Authority found in the registry."
    return curator


# --- Stubbed future tools ---


@mcp.tool()
async def renounce_membership(npub: str) -> str:
    """Citizen self-removal from the Honor Chain via automated PR.

    Not yet implemented — will create a GitHub PR to remove the member
    from members.json.
    """
    raise NotImplementedError(
        "renounce_membership is not yet implemented. "
        "TODO: Automate PR creation for self-removal from members.json."
    )


@mcp.tool()
async def initiate_ban_election(target_npub: str, reason: str) -> str:
    """Initiate a community ban election against a member.

    Not yet implemented — will create a GitHub Issue with a 72-hour
    discussion period and Lightning-funded economic voting.
    """
    raise NotImplementedError(
        "initiate_ban_election is not yet implemented. "
        "TODO: Create GitHub Issue for ban election with economic voting."
    )


@mcp.tool()
async def cast_ban_vote(election_id: str, vote: str, npub: str) -> str:
    """Cast a Lightning-funded vote in an active ban election.

    Not yet implemented — will verify npub membership, validate the
    election is active, and record the vote with a Lightning payment proof.
    """
    raise NotImplementedError(
        "cast_ban_vote is not yet implemented. "
        "TODO: Implement Lightning-funded ban voting mechanism."
    )


if __name__ == "__main__":
    mcp.run()
