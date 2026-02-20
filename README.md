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

### Stubbed (Future)

| Tool | Description |
|------|-------------|
| `renounce_membership(npub)` | Citizen self-removal via automated PR |
| `initiate_ban_election(target_npub, reason)` | Start economic ban voting |
| `cast_ban_vote(election_id, vote, npub)` | Lightning-funded ban vote |

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
