# DPYC Oracle

A free, unauthenticated MCP concierge service for the [DPYC Social Contract](https://github.com/lonniev/dpyc-community). The Oracle answers questions about membership, governance, onboarding, and tax rates by reading the [dpyc-community GitHub registry](https://github.com/lonniev/dpyc-community) live. No credits, no Neon database, no Secure Courier, no payment or credentials required.

## Available Tools

| Tool | Params | Description |
|------|--------|-------------|
| `about()` | — | Extended narration from repo docs (README + GOVERNANCE) |
| `lookup_member(npub)` | `npub: str` | Look up a member by Nostr npub |
| `list_services(probe, kind)` | `probe: bool = True, kind: str = "all"` | Enumerate the live service network from the registry, optionally MCP-handshaking each member for its own self-description and tool inventory |
| `get_tax_rate()` | — | Explains per-Authority ad valorem certification taxation; quotes no rate of its own and redirects to the relevant Authority's `check_price` |
| `economic_model()` | — | Qualitative model of how value flows up the Certification Chain (no hardcoded rates, counts, or revenue figures) |
| `get_rulebook()` | — | GOVERNANCE.md content |
| `how_to_join()` | — | Tier-specific onboarding guide |
| `how_to_add_authority()` | — | End-to-end guide for spinning up a new Tollbooth Authority (fetched live from dpyc-community) |
| `who_is_first_curator()` | — | First Curator's npub and record |
| `network_versions()` | — | Current recommended component versions |
| `network_advisory()` | — | Deployment advisory for operators |
| `service_status()` | — | Runtime version diagnostics |
| `request_citizenship(npub, display_name)` | `npub: str, display_name: str` | Begin citizenship onboarding (issues challenge) |
| `confirm_citizenship(npub, challenge_id, signed_event_json)` | `npub: str, challenge_id: str, signed_event_json: str` | Complete onboarding with signed Nostr event |
| `register_advocate(npub, display_name, service_name, service_url, service_description)` | `npub: str, display_name: str, service_name: str, service_url: str, service_description: str` | Register a community utility service as an Advocate |
| `register_authority(authority_npub, display_name, service_url, upstream_authority_npub)` | `authority_npub: str, display_name: str, service_url: str, upstream_authority_npub: str` | Register a new Authority (called by onboarding flow) |
| `register_operator(operator_npub, display_name, service_url, authority_npub)` | `operator_npub: str, display_name: str, service_url: str, authority_npub: str` | Register a new Operator (called by the sponsoring Authority) |
| `update_operator(operator_npub, service_url, display_name, authority_npub)` | `operator_npub: str, service_url: str = "", display_name: str = "", authority_npub: str = ""` | Update an existing Operator's registry entry (e.g. new MCP endpoint) |
| `deregister_operator(operator_npub, authority_npub)` | `operator_npub: str, authority_npub: str` | Remove an Operator from the registry (Authority disowns the Operator) |
| `check_ban_status(npub)` | `npub: str` | Check if an npub is banned |
| `publish_campaign(author_npub, operator_npub, campaign_json, campaign_name, campaign_markdown)` | `author_npub: str, operator_npub: str, campaign_json: str, campaign_name: str = "", campaign_markdown: str = ""` | Publish a pricing campaign to the DPYC community |
| `list_campaigns(operator_npub, author_npub)` | `operator_npub: str = "", author_npub: str = ""` | List published pricing campaigns, optionally filtered by operator or author |
| `get_campaign(author_npub, operator_npub, slug, format)` | `author_npub: str, operator_npub: str, slug: str, format: str = "json"` | Retrieve a published pricing campaign (JSON or Markdown) |

### Stubbed (Future)

| Tool | Description |
|------|-------------|
| `renounce_membership(npub)` | Citizen self-removal via automated PR |
| `initiate_ban_election(target_npub, reason)` | Start economic ban voting |
| `cast_ban_vote(election_id, vote, npub)` | Lightning-funded ban vote |

## Citizenship Onboarding

New citizens can self-register via Schnorr signature verification:

1. `request_citizenship(npub, display_name)` — issues a cryptographic challenge
2. Sign the challenge with your Nostr nsec (offline, nsec never leaves your device)
3. `confirm_citizenship(npub, challenge_id, signed_event_json)` — verifies signature and auto-commits

On success, the Oracle creates an individual member file at `members/citizens/{npub}.json` in dpyc-community. The CI workflow auto-regenerates `members.json` from individual files.

## Advocate Registration

Advocates are community utility services (e.g., OAuth2 collectors) that provide shared infrastructure but aren't monetized Operators. Registration is Oracle-mediated — no challenge-response needed:

```
register_advocate(
    npub="<service_npub>",
    display_name="My Service",
    service_name="my-service",
    service_url="https://my-service.fastmcp.app",
    service_description="What the service does",
)
```

The Oracle commits `members/advocates/{npub}.json` directly. Peer MCP servers discover the service URL via `resolve_service_by_name()` in the tollbooth-dpyc registry client.

## How to Connect

This service is hosted on Horizon. Add it to your MCP client configuration:

```json
{
  "mcpServers": {
    "dpyc-oracle": {
      "url": "https://dpyc-oracle.fastmcp.app/mcp"
    }
  }
}
```

## Related Repos

The authoritative, always-current roster lives in the registry — call `lookup_member()` / `network_versions()` for live data. The stable source repos:

**Core**
- [dpyc-community](https://github.com/lonniev/dpyc-community) — Registry, governance, and membership data
- [tollbooth-dpyc](https://github.com/lonniev/tollbooth-dpyc) — Python SDK every Operator and Authority builds on
- [tollbooth-sample](https://github.com/lonniev/tollbooth-sample) — Reference Operator template for new services
- [tollbooth-pricing-studio](https://github.com/lonniev/tollbooth-pricing-studio) — iOS app Operators use to design pricing models

**Authorities** (certification chain)
- [tollbooth-authority](https://github.com/lonniev/tollbooth-authority) — Certification + fee ledger
- [tollbooth-authority-northamerica](https://github.com/lonniev/tollbooth-authority-northamerica) — Regional certifier
- [tollbooth-authority-newengland](https://github.com/lonniev/tollbooth-authority-newengland) — Sub-regional certifier

**Operators**
- [thebrain-mcp](https://github.com/lonniev/thebrain-mcp) — Personal Brain knowledge graph
- [excalibur-mcp](https://github.com/lonniev/excalibur-mcp) — X/Twitter posting
- [schwab-mcp](https://github.com/lonniev/schwab-mcp) — Charles Schwab brokerage data
- [taxsort-mcp](https://github.com/lonniev/taxsort-mcp) — Tax sorting + classification
- [optionality-mcp](https://github.com/lonniev/optionality-mcp) — Options analytics
- [cypher-mcp](https://github.com/lonniev/cypher-mcp) — Monetized graph answers (named Cypher over Neo4j/AuraDB)

**Advocates** (shared utilities, unmonetized)
- [tollbooth-oauth2-collector](https://github.com/lonniev/tollbooth-oauth2-collector) — OAuth2 authorization-code collection
- [tollbooth-shortlinks](https://github.com/lonniev/tollbooth-shortlinks) — Ephemeral short URLs for OAuth flows

## License

Apache-2.0
