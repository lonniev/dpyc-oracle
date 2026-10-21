# DPYC Oracle

A free, unauthenticated MCP concierge service for the [DPYC Social Contract](https://github.com/lonniev/dpyc-community). The Oracle answers questions about membership, governance, onboarding, and tax rates by reading the [dpyc-community GitHub registry](https://github.com/lonniev/dpyc-community) live. No credits, no Neon database, no Secure Courier, no payment or credentials required. Registry writes are the exception: each must come on a signed request (see [Signed registry writes](#signed-registry-writes)).

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
| `resolve_service(name, npub)` | `name: str = "", npub: str = ""` | Resolve one service by name or npub (exactly one) to its `npub`, `url`, `name`, `role` and `purchase_mode`. Operators use this through the SDK's `default_oracle_client()` instead of reading GitHub |
| `resolve_authority_for(npub)` | `npub: str` | The certifying Authority (`npub`, `url`, `name`) named by a member's `upstream_authority_npub` |
| `get_relays()` | — | The DPYC Nostr relay set from `dpyc-community/relays.json`, best first; relays the Oracle proved unreachable move to the back, none are dropped |
| `report_relay_failure(relay, reporter_npub, signed_event, mode)` | `relay: str, reporter_npub: str, signed_event: str, mode: str = "unknown"` | Report a relay in the DPYC set as unreachable. The event must be signed by `reporter_npub`; the Oracle then probes the relay itself and only its own probe re-ranks it |
| `request_citizenship(npub, display_name)` | `npub: str, display_name: str` | Begin citizenship onboarding (issues challenge) |
| `confirm_citizenship(npub, challenge_id, signed_event_json)` | `npub: str, challenge_id: str, signed_event_json: str` | Complete onboarding with signed Nostr event |
| `register_advocate(npub, display_name, service_name, service_url, service_description)` | `npub: str, display_name: str, service_name: str, service_url: str, service_description: str` | Register a community utility service as an Advocate; the request must be signed with `npub`'s own key |
| `register_authority(authority_npub, display_name, service_url, upstream_authority_npub)` | `authority_npub: str, display_name: str, service_url: str, upstream_authority_npub: str` | Register a new Authority (called by onboarding flow) |
| `register_operator(operator_npub, display_name, service_url, authority_npub)` | `operator_npub: str, display_name: str, service_url: str, authority_npub: str` | Register a new Operator. Called by the sponsoring Authority when its owner approves an adoption; the request must be signed with `authority_npub`'s key |
| `update_operator(operator_npub, authority_npub, service_url, display_name)` | `operator_npub: str, authority_npub: str, service_url: str = "", display_name: str = ""` | Update an existing Operator's registry entry (e.g. new MCP endpoint). Called by the Authority when its owner approves the operator's update request; the request must be signed with `authority_npub`'s key |
| `deregister_operator(operator_npub, authority_npub)` | `operator_npub: str, authority_npub: str` | Remove an Operator from the registry, when the operator leaves its Authority or the Authority disowns it. Called by the Authority; the request must be signed with `authority_npub`'s key |
| `check_ban_status(npub)` | `npub: str` | Check if an npub is banned |
| `publish_campaign(author_npub, operator_npub, campaign_json, campaign_name, campaign_markdown)` | `author_npub: str, operator_npub: str, campaign_json: str, campaign_name: str = "", campaign_markdown: str = ""` | Publish a pricing campaign to the DPYC community; the request must be signed with `author_npub`'s key |
| `list_campaigns(operator_npub, author_npub)` | `operator_npub: str = "", author_npub: str = ""` | List published pricing campaigns, optionally filtered by operator or author |
| `get_campaign(author_npub, operator_npub, slug, format)` | `author_npub: str, operator_npub: str, slug: str, format: str = "json"` | Retrieve a published pricing campaign (JSON or Markdown) |

### Stubbed (Future)

| Tool | Description |
|------|-------------|
| `renounce_membership(npub)` | Citizen self-removal via automated PR |
| `initiate_ban_election(target_npub, reason)` | Start economic ban voting |
| `cast_ban_vote(election_id, vote, npub)` | Lightning-funded ban vote |

## Signed registry writes

`register_operator`, `update_operator` and `deregister_operator` change who the network trusts, so the Oracle takes them only from the Authority that sponsors the operator. The request must carry a NIP-98 signature (`Authorization: Nostr <base64 kind-27235>`, bound to the request's method, URL and body) made with the key of the `authority_npub` it names. An unsigned request, or one signed by any other key, is refused.

`register_advocate` and `publish_campaign` take the same NIP-98 signature, made with the key of the npub they write: an Advocate registers itself, and a campaign is published under its author's own npub. Anyone holding a key may do either; no one may do it in another npub's name.

Every other Oracle tool answers with no `Authorization` header at all.

Operators never call these tools themselves. An operator asks its Authority (`request_adoption`, `update_operator` or `deregister_operator` on the Authority), and the Authority makes the signed call here once its owner approves, or at once for a deregistration.

## Citizenship Onboarding

New citizens can self-register via Schnorr signature verification:

1. `request_citizenship(npub, display_name)` — issues a cryptographic challenge
2. Sign the challenge with your Nostr nsec (offline, nsec never leaves your device)
3. `confirm_citizenship(npub, challenge_id, signed_event_json)` — verifies signature and auto-commits

On success, the Oracle creates an individual member file at `members/citizens/{npub}.json` in dpyc-community. The CI workflow regenerates `members/read-only-lookup-cache.json` from the individual files.

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

The Oracle commits `members/advocates/{npub}.json` directly and updates `members/read-only-lookup-cache.json`, so the Advocate is discoverable at once. Peer MCP servers discover the service URL through this Oracle's `resolve_service(name=...)`, which tollbooth-dpyc calls as `default_oracle_client().resolve_service(name=...)`.

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

The authoritative, always-current roster lives in the registry — call `list_services()` / `lookup_member()` / `network_versions()` for live data. The stable source repos:

**Core**
- [dpyc-community](https://github.com/lonniev/dpyc-community) — Registry, governance, and membership data
- [tollbooth-dpyc](https://github.com/lonniev/tollbooth-dpyc) — Python SDK every Operator and Authority builds on
- [tollbooth-sample](https://github.com/lonniev/tollbooth-sample) — Reference Operator template for new services
- [tollbooth-pricing-studio](https://github.com/lonniev/tollbooth-pricing-studio) — iOS app Operators use to design pricing models
- [tollbooth-web](https://github.com/lonniev/tollbooth-web) — Shared browser SDK for Operator front ends

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
- [goodearth-mcp](https://github.com/lonniev/goodearth-mcp) — Region-scoped farm climate analytics
- [beesknees-mcp](https://github.com/lonniev/beesknees-mcp) — The Bee's Knees, a multiplayer race to the queen
- [roastify-mcp](https://github.com/lonniev/roastify-mcp) — Roastify coffee catalog and packaging artwork
- [ChartRemotely-mcp](https://github.com/lonniev/ChartRemotely-mcp) — Puts a security on a desktop chart through a paired agent

**Advocates** (shared utilities, unmonetized)
- [tollbooth-oauth2-collector](https://github.com/lonniev/tollbooth-oauth2-collector) — OAuth2 authorization-code collection
- [tollbooth-shortlinks](https://github.com/lonniev/tollbooth-shortlinks) — Ephemeral short URLs for OAuth flows

## License

Apache-2.0
