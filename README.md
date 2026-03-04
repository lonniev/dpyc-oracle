# DPYC Oracle

A free, unauthenticated MCP concierge service for the [DPYC Honor Chain](https://github.com/lonniev/dpyc-community). The Oracle answers questions about membership, governance, onboarding, and tax rates by reading the community registry on GitHub. No payment or credentials required.

## Available Tools

| Tool | Params | Description |
|------|--------|-------------|
| `about()` | — | Extended narration from repo docs (README + GOVERNANCE) |
| `lookup_member(npub)` | `npub: str` | Look up a member by Nostr npub |
| `get_tax_rate()` | — | Current Tollbooth tax rate (2%) |
| `get_rulebook()` | — | GOVERNANCE.md content |
| `how_to_join()` | — | Tier-specific onboarding guide |
| `who_is_first_curator()` | — | First Curator's npub and record |
| `network_versions()` | — | Current recommended component versions |
| `network_advisory()` | — | Deployment advisory for operators |
| `service_status()` | — | Runtime version diagnostics |
| `request_citizenship(npub, display_name)` | `npub: str, display_name: str` | Begin citizenship onboarding (issues challenge) |
| `confirm_citizenship(npub, challenge_id, signed_event_json)` | `npub: str, challenge_id: str, signed_event_json: str` | Complete onboarding with signed Nostr event |
| `economic_model()` | — | Fee schedule and economic model details |

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

## How to Connect

This service is hosted on [FastMCP Cloud](https://www.fastmcp.com). Add it to your MCP client configuration:

```json
{
  "mcpServers": {
    "dpyc-oracle": {
      "url": "https://www.fastmcp.com/server/lonniev/dpyc-oracle"
    }
  }
}
```

## Related Repos

- [dpyc-community](https://github.com/lonniev/dpyc-community) — Registry, governance, and membership data
- [tollbooth-dpyc](https://github.com/lonniev/tollbooth-dpyc) — Python SDK for Tollbooth monetization
- [tollbooth-authority](https://github.com/lonniev/tollbooth-authority) — Authority MCP service for purchase certification
- [thebrain-mcp](https://github.com/lonniev/thebrain-mcp) — Personal Brain MCP service

## License

Apache-2.0
