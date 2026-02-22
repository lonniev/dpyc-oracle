from __future__ import annotations

import base64
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastmcp import FastMCP
from nostr_sdk import Event, PublicKey

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


# -- Citizenship challenge store (ephemeral, in-memory) ----------------------

_CHALLENGE_TTL_SECONDS = 600  # 10 minutes
_CHALLENGE_PREFIX = "DPYC-CITIZENSHIP:"

_challenges: dict[str, dict] = {}


def _prune_expired_challenges() -> None:
    """Remove expired challenges."""
    now = time.time()
    expired = [k for k, v in _challenges.items() if now > v["expires_at"]]
    for k in expired:
        del _challenges[k]


def _validate_npub(npub: str) -> PublicKey:
    """Parse and validate an npub string. Raises ValueError on failure."""
    if not npub.startswith("npub1"):
        raise ValueError(f"Invalid npub format — must start with 'npub1': {npub}")
    return PublicKey.parse(npub)


async def _commit_membership(
    settings: OracleSettings,
    registry: CommunityRegistry,
    npub: str,
    display_name: str,
) -> str:
    """Commit a new citizen directly to main in members.json.

    The Schnorr signature verification is the trust check — no human
    review needed. Returns the commit URL.
    """
    token = settings.github_token
    if not token:
        raise RuntimeError(
            "GitHub token not configured. Set GITHUB_TOKEN env var on "
            "FastMCP Cloud to enable automated membership commits."
        )

    repo = settings.dpyc_community_repo
    api = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    # Fetch the Prime Authority npub for upstream_authority_npub
    curator = await registry.get_first_curator()
    upstream_npub = curator["npub"] if curator else None

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        # 1. Get current members.json from main
        resp = await client.get(f"{api}/contents/members.json?ref=main")
        resp.raise_for_status()
        file_data = resp.json()
        file_sha = file_data["sha"]
        content_b64 = file_data["content"]
        members_json = json.loads(base64.b64decode(content_b64))

        # 2. Add new citizen
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        npub_short = npub[:16]
        new_member = {
            "npub": npub,
            "role": "citizen",
            "status": "active",
            "member_since": today,
            "display_name": display_name,
            "services": [],
            "upstream_authority_npub": upstream_npub,
            "notes": "Admitted via Nostr signature-based citizenship onboarding",
        }
        members_json["members"].append(new_member)
        updated_content = json.dumps(members_json, indent=2) + "\n"
        updated_b64 = base64.b64encode(updated_content.encode()).decode()

        # 3. Commit directly to main
        resp = await client.put(
            f"{api}/contents/members.json",
            json={
                "message": f"[Citizenship] Add {display_name} ({npub_short})",
                "content": updated_b64,
                "sha": file_sha,
            },
        )
        resp.raise_for_status()
        return resp.json()["content"]["html_url"]


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


@mcp.tool()
async def network_versions() -> dict:
    """Get current recommended versions of all Tollbooth components.

    Returns component versions, minimum compatibility, active protocols,
    and a short advisory summary. Data is fetched live from
    network-status.json in the dpyc-community repo.
    """
    _, registry = _ensure_initialized()
    return await registry.get_network_status()


@mcp.tool()
async def network_advisory() -> str:
    """Get current network deployment advisory.

    Returns human-readable guidance on what changed recently, urgent
    upgrades, and actions operators should take. Fetched live from
    ADVISORY.md in the dpyc-community repo.
    """
    _, registry = _ensure_initialized()
    return await registry.get_text("ADVISORY.md")


# --- Citizenship onboarding tools ---


@mcp.tool()
async def request_citizenship(npub: str, display_name: str) -> dict:
    """Begin the citizenship application process.

    Issues a cryptographic challenge that the applicant must sign with
    their Nostr private key (nsec) to prove they own the claimed npub.
    The nsec never leaves the applicant's device.

    Returns a challenge_id, nonce, and signing instructions. The applicant
    signs a Nostr event containing the nonce and submits it via
    confirm_citizenship within 10 minutes.
    """
    # Validate npub format
    try:
        _validate_npub(npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid npub: {exc}"}

    # Check if already a member
    _, registry = _ensure_initialized()
    existing = await registry.lookup_member(npub)
    if existing is not None:
        return {
            "success": False,
            "error": f"Already a member with role '{existing.get('role')}'.",
        }

    # Prune expired challenges and check for pending
    _prune_expired_challenges()
    for ch in _challenges.values():
        if ch["npub"] == npub:
            return {
                "success": False,
                "error": "A pending challenge already exists for this npub. "
                "Complete or wait for it to expire (10 minutes).",
            }

    # Issue challenge
    challenge_id = str(uuid.uuid4())
    nonce = secrets.token_hex(32)
    _challenges[challenge_id] = {
        "npub": npub,
        "display_name": display_name,
        "nonce": nonce,
        "created_at": time.time(),
        "expires_at": time.time() + _CHALLENGE_TTL_SECONDS,
    }

    return {
        "success": True,
        "challenge_id": challenge_id,
        "nonce": nonce,
        "expires_in_seconds": _CHALLENGE_TTL_SECONDS,
        "instructions": (
            "Sign a Nostr event with the content shown below, then call "
            "confirm_citizenship with the signed event JSON.\n\n"
            f"Required event content: {_CHALLENGE_PREFIX}{nonce}\n\n"
            "Example using nostr-sdk:\n"
            "```python\n"
            "from nostr_sdk import Keys, EventBuilder\n"
            "keys = Keys.parse('nsec1YOUR_SECRET_KEY')\n"
            f"event = EventBuilder.text_note('{_CHALLENGE_PREFIX}{nonce}')"
            ".sign_with_keys(keys)\n"
            "print(event.as_json())\n"
            "```"
        ),
    }


@mcp.tool()
async def confirm_citizenship(
    npub: str,
    challenge_id: str,
    signed_event_json: str,
) -> dict:
    """Complete the citizenship application by submitting a signed Nostr event.

    Verifies:
    1. The challenge exists and hasn't expired
    2. The Schnorr signature is valid
    3. The event's pubkey matches the claimed npub
    4. The event content contains the issued nonce
    5. The npub is not already registered

    On success, commits directly to dpyc-community/members.json to register
    the new Citizen immediately.
    """
    _prune_expired_challenges()

    # 1. Validate challenge
    challenge = _challenges.get(challenge_id)
    if challenge is None:
        return {
            "success": False,
            "error": "Challenge not found or expired. Call request_citizenship again.",
        }

    if challenge["npub"] != npub:
        return {
            "success": False,
            "error": "npub does not match the challenge.",
        }

    # 2. Parse and verify the signed event
    try:
        event = Event.from_json(signed_event_json)
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to parse signed event JSON: {exc}",
        }

    try:
        event.verify()
    except Exception as exc:
        return {
            "success": False,
            "error": f"Schnorr signature verification failed: {exc}",
        }

    # 3. Check pubkey matches claimed npub
    try:
        claimed_pk = _validate_npub(npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid npub: {exc}"}

    if event.author().to_hex() != claimed_pk.to_hex():
        return {
            "success": False,
            "error": "Event pubkey does not match the claimed npub.",
        }

    # 4. Check nonce in content
    expected_content = f"{_CHALLENGE_PREFIX}{challenge['nonce']}"
    if expected_content not in event.content():
        return {
            "success": False,
            "error": (
                f"Event content must contain '{expected_content}'. "
                f"Got: '{event.content()[:100]}'"
            ),
        }

    # 5. Re-check membership (race condition guard)
    settings, registry = _ensure_initialized()
    registry.invalidate_cache()
    existing = await registry.lookup_member(npub)
    if existing is not None:
        del _challenges[challenge_id]
        return {
            "success": False,
            "error": "This npub was registered while your challenge was pending.",
        }

    # 6. Commit membership directly to main
    try:
        commit_url = await _commit_membership(
            settings, registry, npub, challenge["display_name"],
        )
    except Exception as exc:
        logger.error("Failed to commit membership: %s", exc)
        return {
            "success": False,
            "error": f"Signature verified but membership commit failed: {exc}",
        }

    # 7. Clean up challenge
    del _challenges[challenge_id]

    return {
        "success": True,
        "status": "admitted",
        "commit_url": commit_url,
        "message": (
            f"Welcome to the DPYC Honor Chain, {challenge['display_name']}! "
            f"Your membership has been registered. You are now a Citizen."
        ),
    }


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
