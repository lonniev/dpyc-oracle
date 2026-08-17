# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

- bootstrap: new read-only tools `get_relays`, `resolve_authority_for(npub)`, and `resolve_service(name|npub)` so an Operator can answer community questions with one MCP call instead of reading GitHub directly. Operators are nsec-only and must never touch the dpyc-community registry themselves — the Oracle is the one GitHub reader. `get_relays` serves `relays.json`; `resolve_authority_for` returns an operator's certifying Authority; `resolve_service` returns `{npub,url,name,role,purchase_mode}`. This closes the fleet-wide bootstrap SPOF where a GitHub-raw 429 stranded cold-starting operators (schwab-mcp, 2026-08-17).
- resilience: `CommunityRegistry` now prefers the authenticated GitHub contents API when a token is present (5,000 req/hr) and serves last-known-good on refresh failure with a short backoff, so a GitHub hiccup degrades to slightly-stale answers instead of failing closed — the same fail-closed behavior that took operators offline.
- ecosystem: add `cypher-mcp` (monetized graph answers — named Cypher over Neo4j/AuraDB) to `ECOSYSTEM_LINKS` and the README "Related Repos" Operators list. The newcomer Operator was absent from the Oracle's static roster; the concierge now points at it alongside the other live services.

## 0.2.15 — 2026-08-10

### Fixed — the onboarding instructions told citizens to call a removed API

`request_citizenship` hands back a runnable snippet, and it said
`EventBuilder.text_note(...).sign_with_keys(keys)`. nostr-sdk 0.45.0 removed that
constructor. Anyone following the Oracle's own instructions with a current nostr-sdk
got an `AttributeError` — the citizenship handshake, broken for new citizens, in the
one place a newcomer is most likely to be. It now reads
`EventBuilder(Kind(1), content).finalize(keys)`, and the tests exercise that path.

`nostr-sdk` was declared `>=0.44.0` with no upper bound, which is how a breaking API
change walked in unannounced. It is pinned to the 0.45 line now, so the code targets
one known API instead of whichever one resolution happens to pick.

### Fixed — CI went red without a commit, and stayed red for two weeks

This repo had no ruff configuration at all, so it inherited whatever ruff's defaults
happened to be — and the workflow installs ruff unpinned. 0.16 enabled new rules by
default and `main` went red on 2026-07-26 with nobody having touched it, then stayed
red, which is why the release below is the first since 0.2.8 despite six versions
being written in the meantime.

The rule set is now declared explicitly, matching excalibur-mcp and thebrain-mcp — the
repos in the fleet that never had this problem, because declaring the set is what makes
a repo immune to a linter's defaults moving underneath it. One real violation (unsorted
imports in a test) is fixed rather than configured away.

`BLE001` sits outside the selected set rather than being silenced by name: the Oracle
reads a remote registry and answers, so a broad catch that returns a situation instead
of raising is the intended shape here, not an oversight.

### Changed — registry publishing, roster, and honest probe naming

MCP Registry publishing via OIDC, cypher-mcp added to the roster, and `list_services`'
probe field renamed `server_version` → `framework_version`, because it reported the
framework's version and calling it the server's invited the wrong conclusion.

### Changed — CI runs the check the deploy runs

`test.yml` inspects the deploy entrypoint, the check Horizon performs at build time. A suite
that never imports the entrypoint cannot fail for the reason a build fails — that gap cost
optionality-mcp four days of silent non-deployment. `release.yml` notes extraction accepts
this CHANGELOG's heading style instead of publishing a 16-byte body.

Note: 0.2.9 through 0.2.14 were written here but never tagged, so none of them shipped a
release. This entry closes that gap going forward; the earlier sections remain as the record.

## [0.2.14] — 2026-06-15

- clarity: `list_services` renames the probe's `server_version` field to `framework_version`. The value is `serverInfo.version`, which for DPYC services is the FastMCP framework version (they don't override it) — not the operator's package release. The new name settles that ambiguity; use `network_versions()` for component release versions. Verified live against the deployed Oracle: 11/13 endpoints handshook clean, the 2 non-MCP OAuth advocate URLs degraded gracefully to `unreachable`.

## [0.2.13] — 2026-06-15

- de-hardcode: `get_tax_rate` no longer fabricates a network-wide `2% / 10 sat` figure. Taxation is ad valorem and **per-Authority** — the tool now explains the model and redirects to the relevant Authority's `check_price` for the live rate. The Oracle, a free docent, quotes no rate it has no authority over. (The certification fee is computed by the SDK's `paid_tool` decorator from each Authority's own pricing model; the Oracle was never in that money path.)
- de-hardcode: `economic_model` drops the fabricated topology (5 authorities / 30 operators / ~200 patrons), the hardcoded 2% fee and cascade percentages, and the `~$1,638/wk` / `$65k BTC` revenue projections. It now gives a qualitative model of how value flows and points at the live sources (`list_services`, `network_versions`, each Authority's `check_price`). The example SVG is kept but explicitly flagged illustrative, not live.
- feat: `list_services(probe=True, kind=...)` — enumerate the live service network from the dpyc-community registry, then handshake each member's MCP endpoint (initialize + tools/list) for its **own** self-description and tool inventory. Nothing about peer services is hardcoded. Resilient: per-service timeout, brief caching, partial results, and a registry-only fallback — a sleeping (cold-start) service never breaks the listing.
- docs: server `INSTRUCTIONS` advertise `list_services` and the docent framing for taxation (Oracle quotes no prices/rates of its own)

## [0.2.12] — 2026-06-14

- voice: replace "Honor Chain" branding throughout the Oracle's user-facing strings, server instructions, README, and package description. The community/agreement is the **DPYC Social Contract**; the authority cascade is the **Certification Chain** (First Curator at its root). Aligns the Oracle — the canonical description other agents read — with the project's preferred voice.

## [0.2.11] — 2026-06-14

- ecosystem: complete `ECOSYSTEM_LINKS` to the full current network — all three Authorities (Prime, North America, New England), all Operators (thebrain, excalibur, schwab, taxsort, optionality), both Advocates (oauth2-collector, shortlinks), the SDK, the sample, and tollbooth-pricing-studio
- ecosystem: rewrite the server `INSTRUCTIONS` "Related repos" block to give canonical entry points and defer the live/full roster to `about()` / `lookup_member()` / `network_versions()`, so the description can't drift out of date
- chore: sync `__version__` (was stuck at 0.2.6) with `pyproject.toml`
- docs: refresh README related-repos list; drop the stale pinned SDK version annotation

## [0.2.10] — 2026-06-14

- feat: campaign tools — `publish_campaign`, `list_campaigns`, `get_campaign` (GitHub-backed CRUD); accept pre-rendered `campaign_markdown`
- feat: operator CRUD — `register_operator`, `update_operator`, `deregister_operator` (Authority-mediated) with `service_url` validation
- feat: `how_to_add_authority` tool — fetches the community guide from dpyc-community
- chore: add ruff lint step to CI

## [0.2.8] — 2026-03-21

- chore: add fastmcp.json for Horizon deployment config
- chore: bump version to 0.2.8

## [0.2.7] — 2026-03-10

- fix: update lookup cache when registering advocates

## [0.2.6] — 2026-03-10

- feat: add register_advocate tool (#16)

## [0.2.5] — 2026-03-08

- chore: bump version to 0.2.5
- Merge pull request #15 from lonniev/refactor/lookup-cache-path
- refactor: update registry path to members/read-only-lookup-cache.json

## [0.2.4] — 2026-03-07

- chore: bump version to 0.2.4
- docs: clarify patron vs operator/authority npub in tool docstrings (#14)

## [0.2.3] — 2026-03-07

- fix: remove curator_royalty_percent from economic_model (#13)

## [0.2.2] — 2026-03-06

- Merge pull request #12 from lonniev/feat/register-authority
- feat: add register_authority tool for Authority onboarding

## [0.2.1] — 2026-03-06

- chore: bump version to 0.2.1
- feat: add check_ban_status tool + fix governance stubs (#11)
- chore: clarify citizen registration tool docstrings (#10)
- Merge pull request #9 from lonniev/chore/ecosystem-links
- chore: add ecosystem_links to service_status and about responses

## [0.2.0] — 2026-03-04

- Merge pull request #8 from lonniev/chore/v0.2.0-file-per-member
- chore: bump to v0.2.0 — file-per-member citizenship writes
- Merge pull request #7 from lonniev/feat/file-per-member-write
- feat: write individual member files instead of monolithic members.json
- Merge pull request #6 from lonniev/feat/economics-svg
- Add economic_model() tool with network economics summary
- Merge pull request #5 from lonniev/feat/service-status
- Add service_status diagnostic tool and fix version mismatch
- Bump to 0.1.1 to trigger Horizon redeploy for GITHUB_TOKEN env
- Merge pull request #4 from lonniev/feat/citizenship-onboarding
- Commit membership directly to main instead of creating PRs
- Implement Nostr signature-based citizenship onboarding
- Add network_versions() and network_advisory() tools (#3)
- Add Tollbooth value proposition to INSTRUCTIONS string (#2)
- Merge pull request #1 from lonniev/feat/initial-scaffold
- Scaffold DPYC Oracle MCP service
- Initial commit

