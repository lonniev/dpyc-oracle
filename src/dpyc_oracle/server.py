from __future__ import annotations

import asyncio
import base64
import importlib.metadata
import json
import logging
import platform
import secrets
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastmcp import Client, FastMCP
from nostr_sdk import Event, PublicKey

from dpyc_oracle import __version__
from dpyc_oracle.config import OracleSettings
from dpyc_oracle.registry import CommunityRegistry

logger = logging.getLogger(__name__)

# Canonical ecosystem repos. The authoritative, always-current member roster
# lives in the dpyc-community registry — call lookup_member()/network_versions()
# for live data. This list is the stable set of source repos people link to.
ECOSYSTEM_LINKS = {
    # Core
    "dpyc_community": "https://github.com/lonniev/dpyc-community",
    "tollbooth_dpyc": "https://github.com/lonniev/tollbooth-dpyc",
    "dpyc_oracle": "https://github.com/lonniev/dpyc-oracle",
    "tollbooth_sample": "https://github.com/lonniev/tollbooth-sample",
    # Authorities (certification chain)
    "tollbooth_authority": "https://github.com/lonniev/tollbooth-authority",
    "tollbooth_authority_northamerica": "https://github.com/lonniev/tollbooth-authority-northamerica",
    "tollbooth_authority_newengland": "https://github.com/lonniev/tollbooth-authority-newengland",
    # Operators
    "thebrain_mcp": "https://github.com/lonniev/thebrain-mcp",
    "excalibur_mcp": "https://github.com/lonniev/excalibur-mcp",
    "schwab_mcp": "https://github.com/lonniev/schwab-mcp",
    "taxsort_mcp": "https://github.com/lonniev/taxsort-mcp",
    "optionality_mcp": "https://github.com/lonniev/optionality-mcp",
    # Advocates (shared utilities, unmonetized)
    "tollbooth_oauth2_collector": "https://github.com/lonniev/tollbooth-oauth2-collector",
    "tollbooth_shortlinks": "https://github.com/lonniev/tollbooth-shortlinks",
    # Pricing app (operator pricing-model editor)
    "tollbooth_pricing_studio": "https://github.com/lonniev/tollbooth-pricing-studio",
    # Oracle MCP endpoint
    "dpyc_oracle_mcp": "https://dpyc-oracle.fastmcp.app/mcp",
}

INSTRUCTIONS = """\
DPYC Oracle — community concierge for the DPYC Social Contract.

DPYC ("Don't Pester Your Customer") is a philosophy and protocol for API \
monetization via Bitcoin Lightning micropayments. Users pre-fund a satoshi \
balance and consume API calls without KYC, stablecoins, or mid-session \
payment popups. Identity is a Nostr keypair (npub), not an email or \
username. Tollbooth monetizes complete business information at the MCP tool \
layer — not raw REST data fragments — using pre-funded Lightning balances \
that eliminate per-request payment ceremonies.

The DPYC Social Contract is a community of Operators and Authorities who \
agree to transparent, auditable economic rules. Operators run MCP services \
and collect Lightning fares via Tollbooths. Authorities certify Operators \
and collect a small tax on every purchase order. The First Curator (Prime \
Authority) sits at the root of the chain and mints the initial cert-sat \
supply. Membership tiers: Citizen → Advocate → Operator → Authority → First Curator.

Advocates are community utility services (e.g., OAuth2 collectors) that \
provide shared infrastructure but aren't monetized Operators or \
certification Authorities. They register via the Oracle's \
register_advocate tool.

Authority onboarding uses a Nostr DM challenge-response protocol: \
candidates call register_authority_npub on their Authority service, \
prove npub ownership via DM, and receive Prime Authority approval. The \
Oracle's register_authority tool commits the new Authority to the \
community registry once the onboarding flow completes.

This Oracle is a free, unauthenticated concierge that answers questions \
about membership, governance, onboarding, and how taxation works by \
reading the dpyc-community registry on GitHub. It does not require \
payment or credentials. It quotes no prices or tax rates of its own — \
those belong to each Operator's and Authority's pricing model. For a \
live figure, call get_tax_rate() to learn how to ask the relevant \
Authority's check_price.

The live ecosystem is read from the dpyc-community registry — never guess at
the roster. Call list_services() to enumerate the live network with each
service's own self-description (MCP handshake), about() for the full set of
ecosystem links, lookup_member() to resolve any npub,
list_canonical_identities via a member service for tool identities, and
network_versions() for current component versions.

Canonical entry points:
- dpyc-community: https://github.com/lonniev/dpyc-community (registry + governance — the authoritative member list)
- tollbooth-dpyc: https://github.com/lonniev/tollbooth-dpyc (Python SDK every operator and Authority builds on)
- tollbooth-authority: https://github.com/lonniev/tollbooth-authority (Authority MCP — certification + fee ledger)
- tollbooth-sample: https://github.com/lonniev/tollbooth-sample (reference Operator template for new services)
- tollbooth-pricing-studio: https://github.com/lonniev/tollbooth-pricing-studio (iOS app operators use to design pricing models)
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
    """Commit a new citizen as an individual file in members/citizens/.

    Creates a single new file — no read-modify-write on the lookup cache,
    so no SHA conflicts when multiple citizens onboard simultaneously.
    CI auto-regenerates the lookup cache on push to main.

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

    file_path = f"members/citizens/{npub}.json"
    content = json.dumps(new_member, indent=2, ensure_ascii=False) + "\n"
    content_b64 = base64.b64encode(content.encode()).decode()

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        resp = await client.put(
            f"{api}/contents/{file_path}",
            json={
                "message": f"[Citizenship] Add {display_name} ({npub_short})",
                "content": content_b64,
            },
        )
        resp.raise_for_status()
        return resp.json()["content"]["html_url"]


async def _commit_authority(
    settings: OracleSettings,
    registry: CommunityRegistry,
    authority_npub: str,
    display_name: str,
    service_url: str,
    upstream_authority_npub: str,
) -> str:
    """Commit a new Authority as an individual file in members/authorities/.

    Same pattern as ``_commit_membership`` but writes role ``"authority"``
    with a service entry. Returns the commit URL.
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

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    npub_short = authority_npub[:16]
    new_member = {
        "npub": authority_npub,
        "role": "authority",
        "status": "active",
        "member_since": today,
        "display_name": display_name,
        "services": [
            {
                "name": "tollbooth-authority",
                "url": service_url,
            },
        ],
        "upstream_authority_npub": upstream_authority_npub,
        "notes": "Admitted via Authority onboarding protocol (Nostr DM challenge-response)",
    }

    file_path = f"members/authorities/{authority_npub}.json"
    content = json.dumps(new_member, indent=2, ensure_ascii=False) + "\n"
    content_b64 = base64.b64encode(content.encode()).decode()

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        resp = await client.put(
            f"{api}/contents/{file_path}",
            json={
                "message": f"[Authority] Add {display_name} ({npub_short})",
                "content": content_b64,
            },
        )
        resp.raise_for_status()
        return resp.json()["content"]["html_url"]


async def _commit_operator(
    settings: OracleSettings,
    registry: CommunityRegistry,
    operator_npub: str,
    display_name: str,
    service_url: str,
    authority_npub: str,
) -> str:
    """Commit a new Operator as an individual file in members/operators/.

    Same pattern as ``_commit_authority`` but writes role ``"operator"``
    with a service entry and the sponsoring Authority's npub.
    Returns the commit URL.
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

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    npub_short = operator_npub[:16]
    new_member = {
        "npub": operator_npub,
        "role": "operator",
        "status": "active",
        "member_since": today,
        "display_name": display_name,
        "services": [
            {
                "name": display_name,
                "url": service_url,
                "description": f"MCP Operator registered under Authority {authority_npub[:16]}...",
            },
        ],
        "upstream_authority_npub": authority_npub,
        "notes": "Registered via Authority-mediated operator registration protocol",
    }

    file_path = f"members/operators/{operator_npub}.json"
    content = json.dumps(new_member, indent=2, ensure_ascii=False) + "\n"
    content_b64 = base64.b64encode(content.encode()).decode()

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        resp = await client.put(
            f"{api}/contents/{file_path}",
            json={
                "message": f"[Operator] Add {display_name} ({npub_short})",
                "content": content_b64,
            },
        )
        resp.raise_for_status()
        return resp.json()["content"]["html_url"]


async def _commit_advocate(
    settings: OracleSettings,
    registry: CommunityRegistry,
    npub: str,
    display_name: str,
    services: list[dict],
) -> str:
    """Commit a new Advocate as an individual file in members/advocates/.

    Same pattern as ``_commit_membership`` but writes role ``"advocate"``
    with required service entries.  After writing the individual file,
    updates ``members/read-only-lookup-cache.json`` so that the new
    advocate is immediately discoverable via ``lookup_member()`` and
    ``resolve_service_by_name()``.  Returns the commit URL for the
    individual file.
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

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    npub_short = npub[:16]
    new_member = {
        "npub": npub,
        "role": "advocate",
        "status": "active",
        "member_since": today,
        "display_name": display_name,
        "services": services,
        "upstream_authority_npub": upstream_npub,
        "notes": "Registered as community utility Advocate via Oracle",
    }

    file_path = f"members/advocates/{npub}.json"
    content = json.dumps(new_member, indent=2, ensure_ascii=False) + "\n"
    content_b64 = base64.b64encode(content.encode()).decode()

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        # 1. Write the individual advocate file
        resp = await client.put(
            f"{api}/contents/{file_path}",
            json={
                "message": f"[Advocate] Add {display_name} ({npub_short})",
                "content": content_b64,
            },
        )
        resp.raise_for_status()
        advocate_url = resp.json()["content"]["html_url"]

        # 2. Update the read-only lookup cache so the advocate is
        #    immediately discoverable without waiting for CI.
        cache_path = "members/read-only-lookup-cache.json"
        try:
            cache_resp = await client.get(f"{api}/contents/{cache_path}")
            cache_resp.raise_for_status()
            cache_meta = cache_resp.json()
            cache_sha = cache_meta["sha"]
            existing_bytes = base64.b64decode(cache_meta["content"])
            cache_data = json.loads(existing_bytes)

            cache_data.setdefault("members", []).append(new_member)
            cache_data["updated_at"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            updated_content = (
                json.dumps(cache_data, indent=2, ensure_ascii=False) + "\n"
            )
            updated_b64 = base64.b64encode(updated_content.encode()).decode()

            cache_put = await client.put(
                f"{api}/contents/{cache_path}",
                json={
                    "message": (
                        f"[Advocate] Update lookup cache: "
                        f"{display_name} ({npub_short})"
                    ),
                    "content": updated_b64,
                    "sha": cache_sha,
                },
            )
            cache_put.raise_for_status()
        except Exception:
            # The individual file was committed successfully.  Log the
            # cache-update failure but don't fail the whole operation —
            # CI will regenerate the cache on the next push to main.
            logger.warning(
                "Advocate %s committed but lookup-cache update failed; "
                "CI will rebuild the cache on next push.",
                npub_short,
            )

        # Invalidate the in-memory registry cache so subsequent
        # lookups fetch the freshly-updated cache from GitHub.
        registry.invalidate_cache()

        return advocate_url


mcp = FastMCP("dpyc-oracle", instructions=INSTRUCTIONS)


@mcp.tool()
async def about() -> str:
    """Extended narration about DPYC, the Social Contract, and the Oracle.

    Fetches README.md and GOVERNANCE.md from the dpyc-community repo and
    assembles a comprehensive context answer.
    """
    _, registry = _ensure_initialized()
    readme = await registry.get_text("README.md")
    governance = await registry.get_text("GOVERNANCE.md")
    links_section = "\n".join(
        f"- **{name}**: {url}" for name, url in ECOSYSTEM_LINKS.items()
    )
    return (
        "# About the DPYC Social Contract\n\n"
        f"{readme}\n\n"
        "---\n\n"
        "# Governance\n\n"
        f"{governance}\n\n"
        "---\n\n"
        "# Ecosystem Links\n\n"
        f"{links_section}"
    )


@mcp.tool()
async def lookup_member(npub: str) -> dict | str:
    """Look up a member by their Nostr npub.

    Can look up any role's npub — citizen, operator, or authority.
    Returns the full member record if found, or a not-found message.
    """
    _, registry = _ensure_initialized()
    member = await registry.lookup_member(npub)
    if member is None:
        return f"No member found with npub: {npub}"
    return member


@mcp.tool()
async def get_tax_rate() -> dict:
    """Explain how Tollbooth certification taxation works.

    Taxation is ad valorem and **per-Authority** — there is no single
    network-wide number, and the Oracle deliberately quotes none. The
    actual fee is the Authority's own accounting, set in its pricing model
    and reported at transaction time. This tool is a docent: it explains
    the model and points to the live source. For the exact figure, query
    the relevant Authority's ``check_price`` for ``certify_credits``.
    """
    return {
        "model": "ad valorem (per-Authority)",
        "summary": (
            "Each Authority sets its own certification fee in its pricing "
            "model and charges it on every certified purchase order. There "
            "is no fixed network-wide rate — the figure belongs to the "
            "Authority, not the Oracle."
        ),
        "how_to_get_the_live_rate": (
            "Ask the Authority directly: call its check_price tool for the "
            "certify_credits capability (free, no proof required). The "
            "Authority reports the exact fee, including any minimum, at "
            "the moment of the purchase order."
        ),
        "cascade": (
            "Authorities are themselves Operators of their upstream "
            "Authority, so a certification fee can cascade up the "
            "Certification Chain to the First Curator. Each hop applies "
            "that Authority's own rate."
        ),
        "discover_authorities": (
            "Use list_services(kind='authority') to enumerate the live "
            "Authorities, or lookup_member()/who_is_first_curator() to "
            "resolve a specific one."
        ),
    }


@mcp.tool()
async def economic_model() -> dict:
    """Explain the DPYC Social Contract economic model — qualitatively.

    Describes how value flows through the network: ad valorem
    certification fees, the cascade up the Certification Chain to the
    First Curator, and where the live numbers actually live. The Oracle
    quotes **no** rates, counts, or revenue figures — those belong to the
    Authorities' pricing models and the live registry, not to a docent.
    Free, unauthenticated.
    """
    return {
        "model": "ad valorem certification fees over a Certification Chain",
        "how_value_flows": [
            "Patrons pre-fund a satoshi balance and consume Operator tools "
            "without per-request payment ceremonies.",
            "Operators collect Lightning fares and pay an ad valorem "
            "certification fee to their sponsoring Authority on each "
            "purchase order.",
            "Authorities are themselves Operators of their upstream "
            "Authority, so certification fees cascade up the chain.",
            "The First Curator (Prime Authority) sits at the root and "
            "receives revenue through that cascade.",
        ],
        "where_the_numbers_live": {
            "rates": (
                "Each Authority sets its own certification fee in its "
                "pricing model. Query an Authority's check_price for the "
                "live figure — see get_tax_rate()."
            ),
            "roster_and_topology": (
                "The live set of Authorities and Operators is the registry, "
                "not a fixed diagram. Use list_services() to enumerate it "
                "and network_versions() for component versions."
            ),
            "revenue": (
                "Throughput and revenue depend on real traffic and the "
                "Bitcoin price; the Oracle does not estimate them."
            ),
        },
        "illustrative_diagram_url": (
            "https://raw.githubusercontent.com/lonniev/dpyc-community"
            "/main/docs/diagrams/dpyc-network-5auth-economics.svg"
        ),
        "diagram_note": (
            "Illustrative example of a hypothetical multi-Authority "
            "network — not live figures. Use list_services() and "
            "network_versions() for the current network."
        ),
    }


@mcp.tool()
async def get_rulebook() -> str:
    """Fetch the DPYC Social Contract governance document.

    Returns the raw markdown of GOVERNANCE.md from the dpyc-community repo.
    """
    _, registry = _ensure_initialized()
    return await registry.get_text("GOVERNANCE.md")


@mcp.tool()
async def how_to_join() -> str:
    """Tier-specific onboarding guide for joining the DPYC Social Contract.

    Covers all five tiers: Citizen, Advocate, Operator, Authority, and
    First Curator. Includes Nostr keygen instructions and practical next
    steps.
    """
    return """\
# How to Join the DPYC Social Contract

## Step 1 — Generate a Nostr Identity

Every member needs a Nostr keypair. Your `npub` is your public identity.

```bash
# Option A: Use a Nostr client like Primal (https://primal.net)
# Create an account → your npub is shown in your profile

# Option B: CLI with nak (https://github.com/fiatjaf/nak)
nak key generate    # prints nsec (private) and npub (public)
```

**Keep your nsec private key safe.** You only share your npub.

> **Multiple keypairs**: Advanced users may generate separate keypairs for
> different roles. The npub you register as a Citizen becomes your
> **patron npub** — the identity used for credit purchases and service
> access. Operators and Authorities typically generate a dedicated keypair
> for their service identity, separate from their patron npub.

## Step 2 — Choose Your Tier

### Citizen (Observer)
- No sponsorship required
- Read governance docs, follow community discussions
- To formalize: ask any Authority to sponsor your PR to the community registry

### Advocate (Community Utility Service)
- For services that provide shared infrastructure (e.g., OAuth2 collectors)
- Not monetized — no Tollbooth fare collection
- Generate a Nostr keypair for the service identity
- Call the Oracle's `register_advocate` tool with your npub, service name, URL, and description
- The Oracle commits your record to `members/advocates/{npub}.json`
- Other MCP services discover your URL via registry lookup

### Operator (Run MCP Services)
- Find a sponsoring Authority willing to vouch for you
- The Authority submits a PR adding `members/operators/{npub}.json` to the registry
- Install `tollbooth-dpyc` in your MCP server for Lightning fare collection
- Configure your BTCPay Server instance for payment processing

### Authority (Curate and Certify Operators)
1. Deploy `tollbooth-authority` as your MCP service
2. Generate a Nostr keypair for the Authority's signing identity
3. Call `register_authority_npub(your_npub)` on your Authority service
4. Reply to the challenge DM in your Nostr client with: `claim = @@@yes@@@`
5. Call `confirm_authority_claim(your_npub)` — this sends an approval request to the Prime Authority
6. Wait for Prime Authority to approve via Nostr DM
7. Call `check_authority_approval(your_npub)` — on success, your Authority is registered in the community and discoverable by Operators

### First Curator (Prime Authority)
- There is exactly one First Curator at the root of the Certification Chain
- This role is not open for application — it is a governance position

## Step 3 — Get Sponsored

1. Introduce yourself in the community (GitHub Issues on dpyc-community)
2. An Authority reviews your intent and submits a PR with your member record
3. CI validates the record format; community reviews the PR
4. Once merged, you are an official member of the DPYC Social Contract

## Useful Links

- Registry: https://github.com/lonniev/dpyc-community
- Tollbooth SDK: https://github.com/lonniev/tollbooth-dpyc
- Authority Service: https://github.com/lonniev/tollbooth-authority
- Primal (Nostr client): https://primal.net
- BTCPay Server: https://btcpayserver.org
"""


@mcp.tool()
async def who_is_first_curator() -> dict | str:
    """Identify the First Curator (Prime Authority) of the Certification Chain.

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


@mcp.tool()
async def how_to_add_authority() -> str:
    """End-to-end guide for spinning up a new Tollbooth Authority.

    Returns the eight-step procedure covering identity, region selection,
    GitHub workspace, dpyc-community registry entry, Neon + BTCPay + Horizon
    deployment, BTCPay credential delivery via Secure Courier, the
    self-registration challenge-response with the parent Authority, and
    pre-funding the cert-fee balance. Fetched live from docs/how-to-add-authority.md
    in the dpyc-community repo.
    """
    _, registry = _ensure_initialized()
    return await registry.get_text("docs/how-to-add-authority.md")


@mcp.tool()
async def service_status() -> dict:
    """Diagnostic: report this service's software versions and runtime info.

    Free, unauthenticated. Use to verify deployment versions across the
    DPYC ecosystem.
    """
    versions: dict[str, str] = {
        "dpyc_oracle": __version__,
        "python": platform.python_version(),
    }
    for pkg in ("fastmcp", "httpx", "nostr-sdk"):
        try:
            versions[pkg.replace("-", "_")] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg.replace("-", "_")] = "unknown"

    return {
        "service": "dpyc-oracle",
        "versions": versions,
        "ecosystem_links": ECOSYSTEM_LINKS,
    }


# -- Live service self-description probe (MCP-to-MCP) -----------------------

_PROBE_TTL_SECONDS = 300
_PROBE_TIMEOUT_SECONDS = 6.0
_INSTRUCTIONS_EXCERPT_CHARS = 600

# url -> (result_dict, fetched_at_monotonic)
_probe_cache: dict[str, tuple[dict, float]] = {}


async def _probe_service(url: str) -> dict:
    """Handshake a peer MCP endpoint for its *own* self-description.

    Performs the standard MCP initialize + tools/list against the service's
    public URL and returns what the service says about itself — server name,
    FastMCP framework version, its self-authored instructions, and its tool
    inventory. Nothing here is hardcoded about the peer.

    Fully defensive: any failure (asleep cold start, unreachable, timeout,
    protocol error) resolves to a structured ``probe_status`` instead of
    raising, because a browsing answer must never fail. Results are cached
    briefly so a visitor doesn't re-hammer every endpoint.
    """
    now = time.monotonic()
    cached = _probe_cache.get(url)
    if cached is not None and (now - cached[1]) < _PROBE_TTL_SECONDS:
        return cached[0]

    async def _handshake() -> dict:
        async with Client(url) as client:
            init = client.initialize_result
            server_info = getattr(init, "serverInfo", None)
            instructions = getattr(init, "instructions", None) or ""
            tools = await client.list_tools()
            pricing_tools = [
                t.name for t in tools
                if t.name.endswith(("check_price", "purchase_credits"))
            ]
            return {
                "probe_status": "live",
                "server_name": getattr(server_info, "name", None),
                # serverInfo.version — for DPYC services this is the FastMCP
                # framework version, not the service's own release (they
                # don't override it). Named accordingly so it isn't mistaken
                # for the operator's package version; use network_versions()
                # for component release versions.
                "framework_version": getattr(server_info, "version", None),
                "self_description": instructions[:_INSTRUCTIONS_EXCERPT_CHARS],
                "tool_count": len(tools),
                "pricing_tools": pricing_tools,
                "pricing_note": (
                    "Live prices come from this service's own check_price "
                    "tool — the Oracle does not quote them."
                ),
            }

    try:
        result = await asyncio.wait_for(_handshake(), _PROBE_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, TimeoutError):
        result = {
            "probe_status": "timeout",
            "note": (
                "No response within the probe window; the service may be "
                "warming up from a cold start. Registry data still applies."
            ),
        }
    except Exception as exc:  # defensive: a browsing answer must never fail
        result = {
            "probe_status": "unreachable",
            "note": f"Could not complete an MCP handshake: {type(exc).__name__}.",
        }

    _probe_cache[url] = (result, now)
    return result


@mcp.tool()
async def list_services(probe: bool = True, kind: str = "all") -> dict:
    """Enumerate the live DPYC service network with self-described summaries.

    Reads the member roster from the dpyc-community registry, then (when
    ``probe=True``) performs a lightweight MCP handshake against each
    member's public service endpoint to fetch that service's *own*
    self-description and tool inventory. Nothing about the services is
    hardcoded here — descriptions are authored by each service, and prices
    come from each Operator/Authority pricing model (call the service's
    ``check_price``).

    Resilient by design: per-service timeout, partial results, brief
    caching, and a registry-only fallback when an endpoint is asleep or
    unreachable. A sleeping service never breaks the listing. Free,
    unauthenticated.

    Args:
        probe: Handshake each endpoint for a live self-description. Set
            False for a fast registry-only listing (no network fan-out).
        kind: Role filter — "all", "operator", "authority", or "advocate".
    """
    _, registry = _ensure_initialized()
    try:
        members = await registry.get_members()
    except Exception as exc:
        return {"success": False, "error": f"Could not read the registry: {exc}"}

    wanted = kind.strip().lower()
    role_filter = {
        "operator": {"operator"},
        "authority": {"authority", "prime_authority"},
        "advocate": {"advocate"},
        "all": {"operator", "authority", "prime_authority", "advocate"},
    }.get(wanted)
    if role_filter is None:
        return {
            "success": False,
            "error": (
                f"Unknown kind '{kind}'. Use all, operator, authority, "
                "or advocate."
            ),
        }

    services: list[dict] = []
    for m in members:
        if m.get("role") not in role_filter:
            continue
        if m.get("status") == "banned":
            continue
        for svc in m.get("services", []) or []:
            url = svc.get("url")
            if not url:
                continue
            services.append(
                {
                    "display_name": m.get("display_name"),
                    "npub": m.get("npub"),
                    "role": m.get("role"),
                    "service_name": svc.get("name"),
                    "url": url,
                    "registry_description": svc.get("description"),
                }
            )

    if probe and services:
        probes = await asyncio.gather(
            *(_probe_service(s["url"]) for s in services),
            return_exceptions=True,
        )
        for s, p in zip(services, probes):
            if isinstance(p, Exception):
                s["live"] = {
                    "probe_status": "unreachable",
                    "note": type(p).__name__,
                }
            else:
                s["live"] = p

    return {
        "success": True,
        "kind": wanted,
        "probed": probe,
        "count": len(services),
        "services": services,
        "note": (
            "Service self-descriptions are authored by each service via its "
            "MCP handshake; certification rates and tool prices come from "
            "each Operator/Authority pricing model (call the service's "
            "check_price). The Oracle hardcodes none of it."
        ),
    }


# --- Citizenship onboarding tools ---


@mcp.tool()
async def request_citizenship(npub: str, display_name: str) -> dict:
    """Begin the citizen registration process (Operator-owned flow).

    This is the **citizen** registration path. Called by the Operator on
    behalf of a patron — invokes the Oracle directly.  No Authority npub
    is required or consulted.  The patron's npub is registered as a
    Citizen in the DPYC community.

    The npub provided here becomes the user's **patron identity** — the
    keypair they will use for credit purchases and service access across
    all Tollbooth-monetized services.

    Not to be confused with **operator** registration, which goes through
    the Authority via a Nostr DM delegation request.

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
    """Complete the citizen registration by submitting a signed Nostr event.

    This is part of the **citizen** registration flow (Operator-owned).
    The Operator calls this on behalf of a patron after the patron has
    signed the cryptographic challenge from request_citizenship.

    Verifies:
    1. The challenge exists and hasn't expired
    2. The Schnorr signature is valid
    3. The event's pubkey matches the claimed npub
    4. The event content contains the issued nonce
    5. The npub is not already registered

    On success, commits directly to dpyc-community/members/citizens/{npub}.json
    to register the new Citizen immediately.
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
            f"Welcome to the DPYC Social Contract, {challenge['display_name']}! "
            f"Your membership has been registered. You are now a Citizen."
        ),
    }


# --- Authority registration (called by Authority onboarding flow) ---


@mcp.tool()
async def register_authority(
    authority_npub: str,
    display_name: str,
    service_url: str,
    upstream_authority_npub: str,
) -> dict:
    """Register a new Authority in the DPYC community registry.

    Called by an Authority service at the end of the onboarding protocol
    (after the candidate proves npub ownership and the Prime Authority
    approves). Commits a new ``members/authorities/{npub}.json`` file to
    dpyc-community on GitHub.

    The full Authority onboarding protocol is a 3-step Nostr DM
    challenge-response flow:
    1. ``register_authority_npub(npub)`` — Authority sends DM challenge
    2. ``confirm_authority_claim(npub)`` — verifies candidate DM, escalates to Prime
    3. ``check_authority_approval(npub)`` — Prime approves, this tool is called

    Parameters:
        authority_npub: Nostr npub of the new Authority curator.
        display_name: Human-readable name for the Authority.
        service_url: Public MCP endpoint URL of the Authority service.
        upstream_authority_npub: npub of the sponsoring Authority (must
            already exist as a prime_authority or authority in the registry).
    """
    # Validate npub format
    try:
        _validate_npub(authority_npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid authority_npub: {exc}"}

    try:
        _validate_npub(upstream_authority_npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid upstream_authority_npub: {exc}"}

    settings, registry = _ensure_initialized()

    # Verify upstream authority exists and has appropriate role
    upstream = await registry.lookup_member(upstream_authority_npub)
    if upstream is None:
        return {
            "success": False,
            "error": (
                f"Upstream authority {upstream_authority_npub[:16]}... "
                "not found in the registry."
            ),
        }
    if upstream.get("role") not in ("prime_authority", "authority"):
        return {
            "success": False,
            "error": (
                f"Upstream member {upstream_authority_npub[:16]}... has role "
                f"'{upstream.get('role')}', not 'authority' or 'prime_authority'."
            ),
        }

    # Check if authority_npub is already registered
    existing = await registry.lookup_member(authority_npub)
    if existing is not None:
        return {
            "success": False,
            "error": (
                f"npub {authority_npub[:16]}... is already registered "
                f"with role '{existing.get('role')}'."
            ),
        }

    # Commit to GitHub
    try:
        registry.invalidate_cache()
        commit_url = await _commit_authority(
            settings,
            registry,
            authority_npub,
            display_name,
            service_url,
            upstream_authority_npub,
        )
    except Exception as exc:
        logger.error("Failed to commit authority membership: %s", exc)
        return {
            "success": False,
            "error": f"Registry commit failed: {exc}",
        }

    return {
        "success": True,
        "status": "registered",
        "commit_url": commit_url,
        "message": (
            f"Authority '{display_name}' ({authority_npub[:16]}...) "
            f"registered under upstream {upstream_authority_npub[:16]}... "
            f"and is now discoverable by Operators."
        ),
    }


# --- Operator registration (Authority-mediated) ---


@mcp.tool()
async def register_operator(
    operator_npub: str,
    display_name: str,
    service_url: str,
    authority_npub: str,
) -> dict:
    """Register a new Operator in the DPYC community registry.

    Called by an Authority service after the operator requests registration.
    The Authority validates the operator's identity and sponsors the
    registration by calling this tool via MCP-to-MCP.

    Parameters:
        operator_npub: Nostr npub of the new Operator.
        display_name: Human-readable name for the Operator service.
        service_url: Public MCP endpoint URL of the Operator service.
        authority_npub: npub of the sponsoring Authority (must already
            exist as an authority or prime_authority in the registry).
    """
    # Validate service_url is provided
    if not service_url or not service_url.strip():
        return {
            "success": False,
            "error": "service_url is required. Provide the operator's public MCP endpoint URL.",
        }

    # Validate npub formats
    try:
        _validate_npub(operator_npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid operator_npub: {exc}"}

    try:
        _validate_npub(authority_npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid authority_npub: {exc}"}

    settings, registry = _ensure_initialized()

    # Verify sponsoring Authority exists and has appropriate role
    upstream = await registry.lookup_member(authority_npub)
    if upstream is None:
        return {
            "success": False,
            "error": (
                f"Sponsoring authority {authority_npub[:16]}... "
                "not found in the registry."
            ),
        }
    if upstream.get("role") not in ("prime_authority", "authority"):
        return {
            "success": False,
            "error": (
                f"Sponsoring member {authority_npub[:16]}... has role "
                f"'{upstream.get('role')}', not 'authority' or 'prime_authority'."
            ),
        }

    # Check if operator_npub is already registered
    existing = await registry.lookup_member(operator_npub)
    if existing is not None:
        return {
            "success": False,
            "error": (
                f"npub {operator_npub[:16]}... is already registered "
                f"with role '{existing.get('role')}'."
            ),
        }

    # Commit to GitHub
    try:
        registry.invalidate_cache()
        commit_url = await _commit_operator(
            settings,
            registry,
            operator_npub,
            display_name,
            service_url,
            authority_npub,
        )
    except Exception as exc:
        logger.error("Failed to commit operator membership: %s", exc)
        return {
            "success": False,
            "error": f"Registry commit failed: {exc}",
        }

    return {
        "success": True,
        "status": "registered",
        "commit_url": commit_url,
        "message": (
            f"Operator '{display_name}' ({operator_npub[:16]}...) "
            f"registered under Authority {authority_npub[:16]}... "
            f"and is now discoverable in the DPYC community."
        ),
    }


async def _update_operator_file(
    settings: OracleSettings,
    registry: CommunityRegistry,
    operator_npub: str,
    updates: dict,
) -> str:
    """Update an existing Operator file in members/operators/.

    Fetches the current file (for the SHA), merges *updates* into the
    existing JSON, and commits the result.  Returns the commit URL.
    """
    token = settings.github_token
    if not token:
        raise RuntimeError("GitHub token not configured.")

    repo = settings.dpyc_community_repo
    api = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    file_path = f"members/operators/{operator_npub}.json"
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        # Fetch current file for SHA and content
        get_resp = await client.get(f"{api}/contents/{file_path}")
        get_resp.raise_for_status()
        file_data = get_resp.json()
        existing_sha = file_data["sha"]
        existing_content = json.loads(
            base64.b64decode(file_data["content"]).decode()
        )

        # Merge updates
        if "service_url" in updates:
            for svc in existing_content.get("services", []):
                svc["url"] = updates["service_url"]
            if not existing_content.get("services"):
                existing_content["services"] = [
                    {"name": existing_content.get("display_name", operator_npub[:16]),
                     "url": updates["service_url"],
                     "description": "MCP Operator endpoint"}
                ]
        if "display_name" in updates:
            existing_content["display_name"] = updates["display_name"]
            for svc in existing_content.get("services", []):
                svc["name"] = updates["display_name"]

        content = json.dumps(existing_content, indent=2, ensure_ascii=False) + "\n"
        content_b64 = base64.b64encode(content.encode()).decode()

        changed = [k for k in updates if updates[k]]
        resp = await client.put(
            f"{api}/contents/{file_path}",
            json={
                "message": f"[Operator] Update {operator_npub[:16]} ({', '.join(changed)})",
                "content": content_b64,
                "sha": existing_sha,
            },
        )
        resp.raise_for_status()
        registry.invalidate_cache()
        return resp.json()["content"]["html_url"]


@mcp.tool()
async def update_operator(
    operator_npub: str,
    service_url: str = "",
    display_name: str = "",
    authority_npub: str = "",
) -> dict:
    """Update an existing Operator's registry entry.

    Used when an Operator moves to a new MCP endpoint, changes its
    display name, or needs to correct a registration.  Must be called
    by the sponsoring Authority (or any Authority).

    Parameters:
        operator_npub: Nostr npub of the Operator to update.
        service_url: New MCP endpoint URL (leave empty to keep current).
        display_name: New display name (leave empty to keep current).
        authority_npub: npub of the requesting Authority (must be a
            registered authority or prime_authority).
    """
    try:
        _validate_npub(operator_npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid operator_npub: {exc}"}

    if authority_npub:
        try:
            _validate_npub(authority_npub)
        except (ValueError, Exception) as exc:
            return {"success": False, "error": f"Invalid authority_npub: {exc}"}

    if not service_url and not display_name:
        return {
            "success": False,
            "error": "Nothing to update. Provide service_url and/or display_name.",
        }

    settings, registry = _ensure_initialized()

    # Verify Authority if provided
    if authority_npub:
        upstream = await registry.lookup_member(authority_npub)
        if upstream is None or upstream.get("role") not in ("prime_authority", "authority"):
            return {
                "success": False,
                "error": f"Authority {authority_npub[:16]}... not found or lacks authority role.",
            }

    # Verify operator exists
    existing = await registry.lookup_member(operator_npub)
    if existing is None:
        return {
            "success": False,
            "error": f"Operator {operator_npub[:16]}... not found in the registry.",
        }
    if existing.get("role") != "operator":
        return {
            "success": False,
            "error": f"Member {operator_npub[:16]}... has role '{existing.get('role')}', not 'operator'.",
        }

    updates = {}
    if service_url:
        updates["service_url"] = service_url
    if display_name:
        updates["display_name"] = display_name

    try:
        commit_url = await _update_operator_file(
            settings, registry, operator_npub, updates
        )
    except Exception as exc:
        logger.error("Failed to update operator: %s", exc)
        return {"success": False, "error": f"Registry update failed: {exc}"}

    return {
        "success": True,
        "status": "updated",
        "commit_url": commit_url,
        "message": (
            f"Operator {operator_npub[:16]}... updated: "
            f"{', '.join(f'{k}={v}' for k, v in updates.items())}."
        ),
    }


async def _delete_operator_file(
    settings: OracleSettings,
    registry: CommunityRegistry,
    operator_npub: str,
) -> str:
    """Delete an Operator's file from members/operators/.

    Fetches the current file SHA (required by GitHub API for deletes),
    then removes the file.  Returns the commit URL.
    """
    token = settings.github_token
    if not token:
        raise RuntimeError("GitHub token not configured.")

    repo = settings.dpyc_community_repo
    api = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    file_path = f"members/operators/{operator_npub}.json"
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        get_resp = await client.get(f"{api}/contents/{file_path}")
        get_resp.raise_for_status()
        existing_sha = get_resp.json()["sha"]

        resp = await client.request(
            "DELETE",
            f"{api}/contents/{file_path}",
            json={
                "message": f"[Operator] Remove {operator_npub[:16]} (deregistered by Authority)",
                "sha": existing_sha,
            },
        )
        resp.raise_for_status()
        registry.invalidate_cache()
        return resp.json()["commit"]["html_url"]


@mcp.tool()
async def deregister_operator(
    operator_npub: str,
    authority_npub: str,
) -> dict:
    """Remove an Operator from the DPYC community registry.

    Called when an Authority disowns an Operator.  An Operator cannot
    exist without a sponsoring Authority, so deregistration removes the
    member file entirely, returning the Operator to initial state.

    Parameters:
        operator_npub: Nostr npub of the Operator to remove.
        authority_npub: npub of the Authority requesting deregistration
            (must be a registered authority or prime_authority).
    """
    try:
        _validate_npub(operator_npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid operator_npub: {exc}"}

    try:
        _validate_npub(authority_npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid authority_npub: {exc}"}

    settings, registry = _ensure_initialized()

    # Verify Authority
    upstream = await registry.lookup_member(authority_npub)
    if upstream is None or upstream.get("role") not in ("prime_authority", "authority"):
        return {
            "success": False,
            "error": f"Authority {authority_npub[:16]}... not found or lacks authority role.",
        }

    # Verify Operator exists
    existing = await registry.lookup_member(operator_npub)
    if existing is None:
        return {
            "success": False,
            "error": f"Operator {operator_npub[:16]}... not found in the registry.",
        }
    if existing.get("role") != "operator":
        return {
            "success": False,
            "error": f"Member {operator_npub[:16]}... has role '{existing.get('role')}', not 'operator'.",
        }

    try:
        commit_url = await _delete_operator_file(settings, registry, operator_npub)
    except Exception as exc:
        logger.error("Failed to deregister operator: %s", exc)
        return {"success": False, "error": f"Deregistration failed: {exc}"}

    return {
        "success": True,
        "status": "deregistered",
        "commit_url": commit_url,
        "message": (
            f"Operator {operator_npub[:16]}... has been removed from the "
            f"DPYC community registry by Authority {authority_npub[:16]}..."
        ),
    }


# --- Advocate registration (Oracle-mediated, no challenge-response) ---


@mcp.tool()
async def register_advocate(
    npub: str,
    display_name: str,
    service_name: str,
    service_url: str,
    service_description: str,
) -> dict:
    """Register a new Advocate in the DPYC community registry.

    Advocates are community utility services that provide shared
    infrastructure (e.g., OAuth2 callback collectors) but aren't
    monetized Operators or certification Authorities.

    This is an Oracle-mediated registration — no Nostr DM
    challenge-response needed. The Oracle operator (Prime Authority)
    trusts the commit via GitHub token.

    Parameters:
        npub: Nostr npub of the Advocate service.
        display_name: Human-readable name for the service.
        service_name: Machine-readable service identifier
            (e.g., "tollbooth-oauth2-collector").
        service_url: Public URL of the service.
        service_description: Short description of what the service does.
    """
    # Validate npub format
    try:
        _validate_npub(npub)
    except (ValueError, Exception) as exc:
        return {"success": False, "error": f"Invalid npub: {exc}"}

    settings, registry = _ensure_initialized()

    # Check if already registered
    existing = await registry.lookup_member(npub)
    if existing is not None:
        return {
            "success": False,
            "error": (
                f"npub {npub[:16]}... is already registered "
                f"with role '{existing.get('role')}'."
            ),
        }

    services = [
        {
            "name": service_name,
            "url": service_url,
            "description": service_description,
        },
    ]

    # Commit to GitHub
    try:
        registry.invalidate_cache()
        commit_url = await _commit_advocate(
            settings, registry, npub, display_name, services,
        )
    except Exception as exc:
        logger.error("Failed to commit advocate membership: %s", exc)
        return {
            "success": False,
            "error": f"Registry commit failed: {exc}",
        }

    return {
        "success": True,
        "status": "registered",
        "commit_url": commit_url,
        "message": (
            f"Advocate '{display_name}' ({npub[:16]}...) registered "
            f"with service '{service_name}' and is now discoverable "
            f"in the DPYC registry."
        ),
    }


# --- Ban status & governance tools ---


@mcp.tool()
async def check_ban_status(npub: str) -> dict:
    """Check whether an npub is banned from the DPYC Social Contract.

    Looks up the member in the community registry and checks whether
    their status is "banned".  Unknown npubs are not considered banned
    (they simply aren't members).

    Free, unauthenticated.  Used by operators during the cold path
    (credit purchases) to enforce community bans.
    """
    try:
        _validate_npub(npub)
    except (ValueError, Exception) as exc:
        return {"banned": False, "error": f"Invalid npub: {exc}"}

    _, registry = _ensure_initialized()
    member = await registry.lookup_member(npub)

    if member is None:
        return {"banned": False, "reason": None}

    status = member.get("status", "active")
    if status == "banned":
        return {
            "banned": True,
            "reason": member.get("ban_reason", "Community ban"),
        }

    return {"banned": False, "reason": None}


@mcp.tool()
async def renounce_membership(npub: str) -> dict:
    """Citizen self-removal from the DPYC Social Contract via automated PR.

    Not yet implemented — will create a GitHub PR to remove the member
    from the registry.
    """
    return {
        "status": "not_yet_implemented",
        "message": "Voluntary membership renunciation is planned but not yet available.",
    }


@mcp.tool()
async def initiate_ban_election(target_npub: str, reason: str) -> dict:
    """Initiate a community ban election against a member.

    Not yet implemented — will create a GitHub Issue with a 72-hour
    discussion period and Lightning-funded economic voting.
    """
    return {
        "status": "not_yet_implemented",
        "message": "Ban elections are planned but not yet available.",
    }


@mcp.tool()
async def cast_ban_vote(election_id: str, vote: str, npub: str) -> dict:
    """Cast a Lightning-funded vote in an active ban election.

    Not yet implemented — will verify npub membership, validate the
    election is active, and record the vote with a Lightning payment proof.
    """
    return {
        "status": "not_yet_implemented",
        "message": "Ban voting is planned but not yet available.",
    }


# ── Campaign sharing ──────────────────────────────────────────────────


def _campaign_slug(name: str) -> str:
    """Convert a campaign name to a URL-safe directory slug."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


def _render_campaign_markdown(campaign: dict) -> str:
    """Render a campaign dict as a human-readable Markdown summary."""
    name = campaign.get("name", "Untitled Campaign")
    operator_name = campaign.get("operator_display_name", "Unknown")
    operator_npub = campaign.get("operator_npub", "")
    created = campaign.get("created_at", "")

    md = f"# {name}\n\n"
    md += f"**Operator:** {operator_name}\n"
    if created:
        md += f"**Created:** {created}\n"
    if operator_npub:
        md += f"**Operator npub:** `{operator_npub[:24]}...`\n"
    md += "\n---\n\n"

    proposal = campaign.get("proposal", {})

    # Tool prices
    tools = proposal.get("tool_prices") or proposal.get("toolPrices") or []
    if tools:
        md += "## Tool Prices\n\n"
        md += "| Tool | Price (sats) | Category |\n"
        md += "|------|-------------|----------|\n"
        for t in tools:
            name_key = t.get("tool_name") or t.get("toolName", "?")
            price = t.get("price_sats") or t.get("priceSats", 0)
            cat = t.get("category", "")
            md += f"| {name_key} | {price} | {cat} |\n"
        md += "\n"

    # Pipeline
    pipeline = proposal.get("pipeline") or []
    if pipeline:
        md += "## Constraint Pipeline\n\n"
        for i, step in enumerate(pipeline):
            md += f"**Step {i + 1}: {step.get('type', '?')}**\n"
            params = step.get("params", {})
            for k, v in sorted(params.items()):
                md += f"- {k}: {v}\n"
            md += "\n"

    # Projections
    proj = (proposal.get("projections")
            or campaign.get("revenue_projections") or {})
    if proj:
        md += "## Revenue Projections\n\n"
        for k, v in sorted(proj.items()):
            md += f"- {k}: {v}\n"
        md += "\n"

    md += "---\n\n"
    md += ("*Published via the [DPYC Oracle]"
           "(https://github.com/lonniev/dpyc-oracle) from "
           "[Pricing Studio]"
           "(https://github.com/lonniev/tollbooth-pricing-studio).*\n")
    return md


async def _commit_campaign_file(
    settings: OracleSettings,
    file_path: str,
    content: str,
    message: str,
) -> str:
    """Commit a single file to dpyc-community via GitHub API."""
    token = settings.github_token
    if not token:
        raise RuntimeError("GitHub token not configured.")

    repo = settings.dpyc_community_repo
    api = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    content_b64 = base64.b64encode(content.encode()).decode()

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        # Check if file exists (need SHA for updates)
        existing = await client.get(f"{api}/contents/{file_path}")
        body: dict = {
            "message": message,
            "content": content_b64,
        }
        if existing.status_code == 200:
            body["sha"] = existing.json()["sha"]

        resp = await client.put(
            f"{api}/contents/{file_path}",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()["content"]["html_url"]


@mcp.tool()
async def publish_campaign(
    author_npub: str,
    operator_npub: str,
    campaign_json: str,
    campaign_name: str = "",
    campaign_markdown: str = "",
) -> dict:
    """Publish a pricing campaign to the DPYC community.

    Commits both a machine-importable JSON file and a human-readable
    Markdown summary to the dpyc-community campaigns directory.

    Args:
        author_npub: The npub of the person who designed the campaign.
        operator_npub: The npub of the operator the campaign is for.
        campaign_json: The full campaign export as a JSON string.
        campaign_name: Optional display name. Derived from JSON if omitted.
        campaign_markdown: Optional pre-rendered Markdown. If omitted, the
            Oracle generates a basic summary from the JSON.
    """
    settings, _ = _ensure_initialized()
    try:
        campaign = json.loads(campaign_json)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e}"}

    name = campaign_name or campaign.get("name", "Untitled")
    slug = _campaign_slug(name)
    campaign["name"] = name

    base_path = f"campaigns/{author_npub}/{operator_npub}/{slug}"

    # Format JSON nicely
    json_content = json.dumps(campaign, indent=2, ensure_ascii=False) + "\n"
    md_content = campaign_markdown if campaign_markdown else _render_campaign_markdown(campaign)

    try:
        json_url = await _commit_campaign_file(
            settings,
            f"{base_path}/campaign.json",
            json_content,
            f"[Campaign] {name} — {slug} (JSON)",
        )
        md_url = await _commit_campaign_file(
            settings,
            f"{base_path}/campaign.md",
            md_content,
            f"[Campaign] {name} — {slug} (Markdown)",
        )
    except Exception as e:
        return {"success": False, "error": f"Commit failed: {e}"}

    return {
        "success": True,
        "campaign_name": name,
        "slug": slug,
        "author_npub": author_npub,
        "operator_npub": operator_npub,
        "json_url": json_url,
        "markdown_url": md_url,
        "message": (
            f"Campaign '{name}' published to dpyc-community. "
            f"JSON: {json_url}"
        ),
    }


@mcp.tool()
async def list_campaigns(
    operator_npub: str = "",
    author_npub: str = "",
) -> dict:
    """List published pricing campaigns from the DPYC community.

    Optionally filter by operator or author npub.

    Args:
        operator_npub: Filter to campaigns for this operator (optional).
        author_npub: Filter to campaigns by this author (optional).
    """
    settings, _ = _ensure_initialized()
    token = settings.github_token
    repo = settings.dpyc_community_repo
    api = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    } if token else {"Accept": "application/vnd.github+json"}

    campaigns = []
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            # List author directories
            resp = await client.get(f"{api}/contents/campaigns")
            if resp.status_code != 200:
                return {"success": True, "campaigns": [], "count": 0}

            authors = [
                item for item in resp.json()
                if item["type"] == "dir" and item["name"].startswith("npub1")
            ]

            for author_dir in authors:
                a_npub = author_dir["name"]
                if author_npub and a_npub != author_npub:
                    continue

                # List operator directories under this author
                resp2 = await client.get(f"{api}/contents/campaigns/{a_npub}")
                if resp2.status_code != 200:
                    continue

                for op_dir in resp2.json():
                    if op_dir["type"] != "dir" or not op_dir["name"].startswith("npub1"):
                        continue
                    o_npub = op_dir["name"]
                    if operator_npub and o_npub != operator_npub:
                        continue

                    # List campaign directories
                    resp3 = await client.get(
                        f"{api}/contents/campaigns/{a_npub}/{o_npub}"
                    )
                    if resp3.status_code != 200:
                        continue

                    for camp_dir in resp3.json():
                        if camp_dir["type"] != "dir":
                            continue
                        campaigns.append({
                            "slug": camp_dir["name"],
                            "author_npub": a_npub,
                            "operator_npub": o_npub,
                            "path": f"campaigns/{a_npub}/{o_npub}/{camp_dir['name']}",
                        })

    except Exception as e:
        return {"success": False, "error": f"Failed to list campaigns: {e}"}

    return {"success": True, "campaigns": campaigns, "count": len(campaigns)}


@mcp.tool()
async def get_campaign(
    author_npub: str,
    operator_npub: str,
    slug: str,
    format: str = "json",
) -> dict:
    """Retrieve a published pricing campaign.

    Args:
        author_npub: The campaign author's npub.
        operator_npub: The target operator's npub.
        slug: The campaign slug (directory name).
        format: "json" for importable data, "markdown" for readable summary.
    """
    settings, _ = _ensure_initialized()
    token = settings.github_token
    repo = settings.dpyc_community_repo
    api = f"https://api.github.com/repos/{repo}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    } if token else {"Accept": "application/vnd.github+json"}

    ext = "md" if format == "markdown" else "json"
    file_path = f"campaigns/{author_npub}/{operator_npub}/{slug}/campaign.{ext}"

    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            resp = await client.get(f"{api}/contents/{file_path}")
            if resp.status_code == 404:
                return {
                    "success": False,
                    "error": f"Campaign not found: {slug}",
                }
            resp.raise_for_status()
            content_b64 = resp.json()["content"]
            content = base64.b64decode(content_b64).decode()

            if format == "json":
                return {
                    "success": True,
                    "campaign": json.loads(content),
                    "slug": slug,
                }
            else:
                return {
                    "success": True,
                    "markdown": content,
                    "slug": slug,
                }

    except Exception as e:
        return {"success": False, "error": f"Failed to retrieve campaign: {e}"}


if __name__ == "__main__":
    mcp.run()
