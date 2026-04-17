# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

