"""Phase 1 爬蟲的測試。

MediaWiki API 全部用 respx 假造,不打真的 Wikipedia:測試不能依賴即時的線上狀態。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from wiki_pipeline.config import CrawlConfig, PipelineConfig
from wiki_pipeline.scrape import crawl, export_network_json
from wiki_pipeline.state import StateStore
from wiki_pipeline.wiki_api import WikiClient

API = "https://zh.wikipedia.org/w/api.php"

# 條目 → 外連。「圖論」故意分兩頁回傳,測 continue 翻頁。
LINKS: dict[str, list[list[str]]] = {
    "圖論": [["網絡科學", "演算法"], ["拓撲學"]],
    "網絡科學": [["圖論", "複雜網絡"]],
    "演算法": [["圖論"]],
    "拓撲學": [[]],
    "複雜網絡": [[]],
}

# 別名 → 正式標題。真實的 zh 維基同時有 redirect(graph theory)與簡繁轉換(图论)兩種。
REDIRECTS = {"graph theory": "圖論", "图论": "圖論"}


def _links_response(title: str, page: int) -> dict:
    pages_for_title = LINKS.get(title, [[]])
    links = pages_for_title[page] if page < len(pages_for_title) else []
    body: dict = {"query": {"pages": [{"title": t, "ns": 0} for t in links]}}
    if page + 1 < len(pages_for_title):
        body["continue"] = {"gplcontinue": f"{title}|{page + 1}", "continue": "gplcontinue||"}
    return body


def _make_api(failing_titles: set[str] | None = None):
    """回傳一個依 titles 參數作答的假 API handler。"""
    failing = failing_titles or set()

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params

        # 標題收斂查詢(沒有 generator、也不是 extracts)
        if "generator" not in params and params.get("prop") != "extracts":
            titles = params["titles"].split("|")
            converted = [{"from": t, "to": REDIRECTS[t]} for t in titles if t in REDIRECTS]
            return httpx.Response(
                200,
                json={
                    "query": {
                        "converted": converted,
                        "pages": [{"title": REDIRECTS.get(t, t)} for t in titles],
                    }
                },
            )

        if params.get("prop") == "extracts":
            titles = params["titles"].split("|")
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [{"title": t, "extract": f"{t}的簡介。"} for t in titles],
                    }
                },
            )

        requested = params["titles"]
        if requested in failing:
            return httpx.Response(500, text="boom")

        canonical = REDIRECTS.get(requested, requested)
        cont = params.get("gplcontinue")
        page = int(cont.split("|")[1]) if cont else 0
        body = _links_response(canonical, page)
        if canonical != requested:
            body["query"]["redirects"] = [{"from": requested, "to": canonical}]
        return httpx.Response(200, json=body)

    return handler


def _config(seeds: list[str], depth: int, tmp_path) -> PipelineConfig:
    return PipelineConfig(
        crawl=CrawlConfig(seeds=seeds, depth=depth, concurrency=2),
        output_dir=tmp_path / "output",
        state_dir=tmp_path / "state",
    )


def _run(config: PipelineConfig, store: StateStore, **kwargs):
    async def main():
        async with WikiClient(concurrency=2, max_retries=1) as client:
            return await crawl(config, store, client=client, **kwargs)

    return asyncio.run(main())


@pytest.fixture
def store(tmp_path):
    with StateStore(tmp_path / "state" / "pipeline.sqlite") as s:
        yield s


@respx.mock
def test_depth_1_expands_only_seeds(store: StateStore, tmp_path) -> None:
    respx.get(API).mock(side_effect=_make_api())
    stats = _run(_config(["圖論"], 1, tmp_path), store)

    assert stats.expanded == 1
    # 種子的外連(含翻頁那一頁)都成為節點,但不再往下展開
    titles = {t for _, t in store.iter_articles()}
    assert titles == {"圖論", "網絡科學", "演算法", "拓撲學"}
    assert store.link_count() == 3
    assert store.pending(1) == []


@respx.mock
def test_depth_2_expands_second_level(store: StateStore, tmp_path) -> None:
    respx.get(API).mock(side_effect=_make_api())
    stats = _run(_config(["圖論"], 2, tmp_path), store)

    assert stats.expanded == 4  # 圖論 + 網絡科學 + 演算法 + 拓撲學
    titles = {t for _, t in store.iter_articles()}
    assert "複雜網絡" in titles  # 第二層才發現得到
    graph_idx = store.get_idx("圖論")
    net_idx = store.get_idx("網絡科學")
    assert net_idx in store.outgoing(graph_idx)
    assert graph_idx in store.outgoing(net_idx)  # 雙向連結各自記一條有向邊


@respx.mock
def test_redirect_is_resolved_to_canonical_title(store: StateStore, tmp_path) -> None:
    respx.get(API).mock(side_effect=_make_api())
    _run(_config(["graph theory"], 1, tmp_path), store)

    titles = {t for _, t in store.iter_articles()}
    assert "graph theory" not in titles  # 不會產生重複節點
    assert "圖論" in titles
    assert store.resolve("graph theory") == "圖論"
    assert store.is_done("graph theory") and store.is_done("圖論")


@respx.mock
def test_simplified_and_traditional_titles_collapse_to_one_node(
    store: StateStore, tmp_path
) -> None:
    """zh 維基的正式標題簡繁混雜,同一條目的兩種寫法必須收斂成同一個節點。"""
    respx.get(API).mock(side_effect=_make_api())
    _run(_config(["图论", "圖論"], 1, tmp_path), store)

    titles = {t for _, t in store.iter_articles()}
    assert "图论" not in titles
    assert store.resolve("图论") == "圖論"
    assert store.status_counts().get("failed") is None


@respx.mock
def test_failed_titles_are_recorded_then_retried_on_resume(store: StateStore, tmp_path) -> None:
    config = _config(["圖論"], 2, tmp_path)

    respx.get(API).mock(side_effect=_make_api(failing_titles={"網絡科學"}))
    first = _run(config, store)
    assert first.failed == 1
    assert store.status_counts()["failed"] == 1

    # 第二次跑:API 恢復正常,失敗的條目要被放回佇列並補完
    respx.get(API).mock(side_effect=_make_api())
    second = _run(config, store)
    assert second.expanded == 1  # 只補那一個,已完成的不重爬
    assert store.status_counts().get("failed") is None
    assert "複雜網絡" in {t for _, t in store.iter_articles()}


@respx.mock
def test_resume_does_not_refetch_completed_titles(store: StateStore, tmp_path) -> None:
    route = respx.get(API).mock(side_effect=_make_api())
    config = _config(["圖論"], 1, tmp_path)
    _run(config, store)
    calls_after_first = route.call_count

    _run(config, store)
    assert route.call_count == calls_after_first  # 完全沒有再打 API


@respx.mock
def test_export_json_keeps_legacy_shape(store: StateStore, tmp_path) -> None:
    respx.get(API).mock(side_effect=_make_api())
    config = _config(["圖論"], 1, tmp_path)
    _run(config, store)

    path = export_network_json(store, config.output_dir / "wiki_network.json")
    records = json.loads(path.read_text(encoding="utf-8"))

    assert {r["Title"] for r in records} == {"圖論", "網絡科學", "演算法", "拓撲學"}
    assert set(records[0]) == {"Index", "Title", "Directed_Index"}
    all_indices = {r["Index"] for r in records}
    for record in records:
        # 不能有指向資料集之外的 Directed_Index
        assert set(record["Directed_Index"]) <= all_indices


@respx.mock
def test_non_article_namespaces_are_filtered(store: StateStore, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {"title": "網絡科學", "ns": 0},
                        {"title": "Category:數學", "ns": 14},
                        {"title": "Template:數學", "ns": 10},
                    ]
                }
            },
        )

    respx.get(API).mock(side_effect=handler)
    _run(_config(["圖論"], 1, tmp_path), store)

    titles = {t for _, t in store.iter_articles()}
    assert titles == {"圖論", "網絡科學"}
