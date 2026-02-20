from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from dpyc_oracle.registry import CommunityRegistry, RegistryError

SAMPLE_MEMBERS = {
    "members": [
        {
            "npub": "npub1alice",
            "role": "operator",
            "status": "active",
            "display_name": "Alice",
            "services": [],
        },
        {
            "npub": "npub1curator",
            "role": "prime_authority",
            "status": "active",
            "display_name": "The Curator",
            "services": [],
        },
    ]
}

SAMPLE_GOVERNANCE = "# Governance\n\nRules go here."


@pytest.fixture
def registry():
    return CommunityRegistry(
        base_url="https://example.com/repo/main",
        cache_ttl_seconds=60,
    )


def _mock_response(json_data=None, text_data=None, status_code=200):
    resp = AsyncMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=Mock(), response=resp
        )
    if json_data is not None:
        resp.json.return_value = json_data
    if text_data is not None:
        resp.text = text_data
    return resp


@pytest.mark.asyncio
async def test_get_members_parses_wrapper(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        members = await registry.get_members()
    assert len(members) == 2
    assert members[0]["npub"] == "npub1alice"


@pytest.mark.asyncio
async def test_lookup_member_found(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        member = await registry.lookup_member("npub1alice")
    assert member is not None
    assert member["display_name"] == "Alice"


@pytest.mark.asyncio
async def test_lookup_member_not_found(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        member = await registry.lookup_member("npub1unknown")
    assert member is None


@pytest.mark.asyncio
async def test_get_first_curator(registry):
    with patch.object(
        registry._client, "get", return_value=_mock_response(json_data=SAMPLE_MEMBERS)
    ):
        curator = await registry.get_first_curator()
    assert curator is not None
    assert curator["role"] == "prime_authority"
    assert curator["display_name"] == "The Curator"


@pytest.mark.asyncio
async def test_get_text_returns_markdown(registry):
    with patch.object(
        registry._client,
        "get",
        return_value=_mock_response(text_data=SAMPLE_GOVERNANCE),
    ):
        text = await registry.get_text("GOVERNANCE.md")
    assert "# Governance" in text


@pytest.mark.asyncio
async def test_cache_hit_within_ttl(registry):
    mock_get = AsyncMock(return_value=_mock_response(json_data=SAMPLE_MEMBERS))
    with patch.object(registry._client, "get", mock_get):
        await registry.get_members()
        await registry.get_members()
    assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_cache_expired_refetches(registry):
    registry._ttl = 0  # expire immediately
    mock_get = AsyncMock(return_value=_mock_response(json_data=SAMPLE_MEMBERS))
    with patch.object(registry._client, "get", mock_get):
        await registry.get_members()
        # Force cache to be stale by setting fetch time in the past
        for key in registry._json_cache:
            data, _ = registry._json_cache[key]
            registry._json_cache[key] = (data, time.monotonic() - 10)
        await registry.get_members()
    assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_http_error_raises_registry_error(registry):
    with patch.object(
        registry._client,
        "get",
        return_value=_mock_response(status_code=500),
    ):
        with pytest.raises(RegistryError, match="Failed to fetch"):
            await registry.get_members()
