"""瀏覽量相關的測試:API 抓取、半月彙總、續傳。"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest
import respx

from wiki_pipeline.config import CrawlConfig, PageviewsConfig, PipelineConfig
from wiki_pipeline.pageviews import (
    average_pageviews,
    half_month_key,
    to_community_daily,
    to_half_month,
)
from wiki_pipeline.stages import run_extracts_stage, run_pageviews_stage
from wiki_pipeline.state import StateStore
from wiki_pipeline.wiki_api import WikiClient

PAGEVIEWS_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
WIKI_API = "https://zh.wikipedia.org/w/api.php"


# --- 本地彙總 ---------------------------------------------------------------


def test_half_month_key_splits_on_the_16th() -> None:
    assert half_month_key("2026-08-01") == "2026-08-01"
    assert half_month_key("2026-08-15") == "2026-08-01"
    assert half_month_key("2026-08-16") == "2026-08-16"
    assert half_month_key("2026-08-31") == "2026-08-16"


def test_to_half_month_sums_each_period() -> None:
    daily = [
        ("2026-08-01", 10),
        ("2026-08-15", 5),
        ("2026-08-16", 100),
        ("2026-09-02", 7),
    ]
    assert to_half_month(daily) == [
        ("2026-08-01", 15),
        ("2026-08-16", 100),
        ("2026-09-01", 7),
    ]


def test_half_month_total_matches_daily_total() -> None:
    daily = [(f"2026-08-{day:02d}", day) for day in range(1, 32)]
    assert sum(v for _, v in to_half_month(daily)) == sum(v for _, v in daily)


def test_average_pageviews() -> None:
    assert average_pageviews([("2026-08-01", 10), ("2026-08-02", 20)]) == 15
    assert average_pageviews([]) == 0.0


def test_community_daily_sums_member_nodes() -> None:
    result = to_community_daily(
        community_of={1: 7, 2: 7, 3: 9},
        pageviews_of={
            1: [("2026-08-01", 10)],
            2: [("2026-08-01", 5), ("2026-08-02", 1)],
            3: [("2026-08-01", 100)],
            4: [("2026-08-01", 999)],  # 不屬於任何社群 → 忽略
        },
    )
    assert result[7] == [("2026-08-01", 15), ("2026-08-02", 1)]
    assert result[9] == [("2026-08-01", 100)]
    assert 4 not in result


# --- 設定 -------------------------------------------------------------------


def test_date_range_respects_lag_and_days() -> None:
    config = PageviewsConfig(days=30, lag_days=2)
    start, end = config.date_range(date(2026, 8, 18))
    assert end == "20260816"  # 落後兩天
    assert start == "20260718"  # 含頭含尾共 30 天


# --- 抓取(假 API)---------------------------------------------------------


def _config(tmp_path, days: int = 3) -> PipelineConfig:
    return PipelineConfig(
        crawl=CrawlConfig(seeds=["圖論"], depth=1, concurrency=2),
        pageviews=PageviewsConfig(days=days, lag_days=2, concurrency=2),
        output_dir=tmp_path / "output",
        state_dir=tmp_path / "state",
    )


@pytest.fixture
def store(tmp_path):
    with StateStore(tmp_path / "state" / "pipeline.sqlite") as s:
        s.add_article("图论")
        s.add_article("网络科学")
        s.conn.commit()
        yield s


def _pageviews_response(request: httpx.Request) -> httpx.Response:
    title = request.url.path.split("/")[-4]
    if title == "网络科学":
        return httpx.Response(404, json={"detail": "no data"})
    return httpx.Response(
        200,
        json={
            "items": [
                {"timestamp": "2026081400", "views": 10},
                {"timestamp": "2026081500", "views": 20},
                {"timestamp": "2026081600", "views": 30},
            ]
        },
    )


@respx.mock
def test_fetch_pageviews_parses_and_handles_404() -> None:
    respx.get(url__startswith=PAGEVIEWS_URL).mock(side_effect=_pageviews_response)

    async def main():
        async with WikiClient(concurrency=2, max_retries=1) as client:
            found = await client.fetch_pageviews("图论", "20260814", "20260816")
            empty = await client.fetch_pageviews("网络科学", "20260814", "20260816")
            return found, empty

    found, empty = asyncio.run(main())
    assert found == [("2026-08-14", 10), ("2026-08-15", 20), ("2026-08-16", 30)]
    assert empty == []  # 沒有資料不是錯誤


@respx.mock
def test_pageviews_stage_stores_and_resumes(store: StateStore, tmp_path) -> None:
    route = respx.get(url__startswith=PAGEVIEWS_URL).mock(side_effect=_pageviews_response)
    config = _config(tmp_path)

    stats = asyncio.run(run_pageviews_stage(config, today=date(2026, 8, 18)))
    assert stats.total == 2
    assert stats.fetched == 1 and stats.empty == 1
    assert stats.rows == 3
    assert store.get_pageviews(store.get_idx("图论")) == [
        ("2026-08-14", 10),
        ("2026-08-15", 20),
        ("2026-08-16", 30),
    ]

    calls = route.call_count
    again = asyncio.run(run_pageviews_stage(config, today=date(2026, 8, 18)))
    assert again.total == 0  # 兩個都做過了
    assert route.call_count == calls  # 沒有再打 API


@respx.mock
def test_pageviews_stage_retries_failed_articles(store: StateStore, tmp_path) -> None:
    respx.get(url__startswith=PAGEVIEWS_URL).mock(return_value=httpx.Response(500, text="boom"))
    config = _config(tmp_path)

    stats = asyncio.run(run_pageviews_stage(config, today=date(2026, 8, 18)))
    assert stats.failed == 2
    assert store.pageview_status_counts() == {"failed": 2}

    respx.get(url__startswith=PAGEVIEWS_URL).mock(side_effect=_pageviews_response)
    retry = asyncio.run(run_pageviews_stage(config, today=date(2026, 8, 18)))
    assert retry.total == 2  # 失敗的會被重抓
    assert store.pageview_status_counts() == {"done": 2}


@respx.mock
def test_extracts_stage_marks_missing_articles(store: StateStore, tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"query": {"pages": [{"title": "图论", "extract": "圖論是數學的一個分支。"}]}},
        )

    route = respx.get(WIKI_API).mock(side_effect=handler)
    config = _config(tmp_path)

    stats = asyncio.run(run_extracts_stage(config))
    assert stats.fetched == 1
    assert stats.missing == 1  # 网络科学 沒回傳 → 記成問過了

    idx = store.get_idx("图论")
    assert store.get_extract(idx).startswith("圖論")

    calls = route.call_count
    assert asyncio.run(run_extracts_stage(config)).total == 0
    assert route.call_count == calls  # 查不到的條目也不會再問一次


@respx.mock
def test_fetch_extracts_rejects_oversized_batch() -> None:
    """TextExtracts 一次只回 20 筆,而且超過的部分不會報錯、只會靜靜地沒有 extract ——
    所以呼叫端一次丟超過 20 個標題必須當場擋下來,不然會靜默漏資料。"""

    async def main():
        async with WikiClient(concurrency=1) as client:
            await client.fetch_extracts([f"條目{i}" for i in range(21)])

    with pytest.raises(ValueError, match="20"):
        asyncio.run(main())


@respx.mock
def test_extracts_retry_missing_refetches_null_rows(store: StateStore, tmp_path) -> None:
    config = _config(tmp_path)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        # 第一次都查不到,第二次才回資料(模擬抓取邏輯修好後重抓)
        if calls["n"] == 1:
            return httpx.Response(200, json={"query": {"pages": []}})
        return httpx.Response(
            200, json={"query": {"pages": [{"title": "图论", "extract": "圖論簡介"}]}}
        )

    respx.get(WIKI_API).mock(side_effect=handler)
    assert asyncio.run(run_extracts_stage(config)).missing == 2
    assert asyncio.run(run_extracts_stage(config)).total == 0  # 預設不會重問

    again = asyncio.run(run_extracts_stage(config, retry_missing=True))
    assert again.total == 2
    assert store.get_extract(store.get_idx("图论")) == "圖論簡介"
