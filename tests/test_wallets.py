from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from tollbooth.web_search import BRAVE_URL, Hit

from dpyc_oracle import wallets

CATALOG = {
    "query": "lightning wallet",
    "show": 3,
    "credit": "Marks are their owners'.",
    "wallets": [
        {"id": "wos", "name": "Wallet of Satoshi", "aliases": ["WoS"], "pinned": True, "line": "a",
         "custody": "self-custodial", "buys_in_app": False, "homepage": "https://w", "logo": "data:"},
        {"id": "phoenix", "name": "Phoenix", "aliases": [], "line": "b",
         "custody": "self-custodial", "buys_in_app": False, "homepage": "https://p", "logo": "data:"},
        {"id": "blink", "name": "Blink", "aliases": [], "line": "c",
         "custody": "custodial", "buys_in_app": False, "homepage": "https://b", "logo": "data:"},
        {"id": "strike", "name": "Strike", "aliases": [], "line": "d",
         "custody": "custodial", "buys_in_app": True, "homepage": "https://s", "logo": "data:"},
    ],
}


@pytest.fixture(autouse=True)
def _fresh():
    wallets.clear_cache()
    yield
    wallets.clear_cache()


def _r(text: str) -> Hit:
    return Hit(title=text, url="https://example.com/" + text.replace(" ", "-"))


def _raw(hit: Hit) -> dict:
    return {"title": hit.title, "url": hit.url, "description": "", "extra_snippets": []}


def test_pinned_first_then_by_results_mentioning():
    ranked = wallets.rank(CATALOG["wallets"], [_r("Strike and Blink"), _r("Strike review"), _r("Phoenix")])
    assert [w["id"] for w in ranked] == ["wos", "strike", "phoenix", "blink"]
    assert ranked[1]["mentions"] == 2


def test_a_result_counts_once_however_often_it_names_a_wallet():
    ranked = wallets.rank(CATALOG["wallets"], [_r("Phoenix Phoenix Phoenix"), _r("Blink"), _r("Blink")])
    assert {w["id"]: w["mentions"] for w in ranked}["phoenix"] == 1
    assert [w["id"] for w in ranked][1] == "blink"


def test_names_match_whole_words_only():
    ranked = wallets.rank(CATALOG["wallets"], [_r("blinking lights, Strikeout")])
    assert all(w["mentions"] == 0 for w in ranked)


def test_aliases_and_snippets_count():
    ranked = wallets.rank(CATALOG["wallets"], [Hit(title="x", url="https://x", snippets=("try wos today",))])
    assert ranked[0]["mentions"] == 1


def test_ties_keep_catalog_order():
    assert [w["id"] for w in wallets.rank(CATALOG["wallets"], [])] == ["wos", "phoenix", "blink", "strike"]


async def test_without_a_key_the_catalog_order_answers():
    out = await wallets.lightning_wallets(CATALOG, None, 86400)
    assert out["ranked_by"] == "catalog"
    assert [w["id"] for w in out["wallets"]] == ["wos", "phoenix", "blink"]
    assert "mentions" not in out["wallets"][0]
    assert "aliases" not in out["wallets"][0]


@pytest.mark.parametrize("status", [429, 500])
async def test_brave_refusing_falls_back_and_never_leaks_the_key(status, caplog):
    resp = httpx.Response(status, request=httpx.Request("GET", BRAVE_URL), text="secret-key echoed")
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=resp)):
        out = await wallets.lightning_wallets(CATALOG, "secret-key", 86400)
    assert out["ranked_by"] == "catalog"
    assert "secret-key" not in caplog.text
    assert "secret-key" not in str(out)


async def test_brave_ranks_and_the_answer_is_cached():
    body = {"web": {"results": [_raw(_r("Strike")), _raw(_r("Strike and Blink"))]}}
    resp = httpx.Response(200, request=httpx.Request("GET", BRAVE_URL), json=body)
    get = AsyncMock(return_value=resp)
    with patch("httpx.AsyncClient.get", get):
        first = await wallets.lightning_wallets(CATALOG, "k", 86400)
        second = await wallets.lightning_wallets(CATALOG, "k", 86400)
    assert first["ranked_by"] == "brave"
    assert [w["id"] for w in first["wallets"]] == ["wos", "strike", "blink"]
    assert second is first
    assert get.await_count == 1
    assert get.await_args.kwargs["headers"]["X-Subscription-Token"] == "k"
