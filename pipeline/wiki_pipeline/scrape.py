"""Phase 1 — 從種子條目爬出連結圖。

改寫自 `docs/legacy/data_factory/build_data.py` 的
`get_article_links` / `add_article` / `process_article` / `build_network` / `safe_write_json`。

與舊版的差異:
- 舊版是遞迴 DFS + 序列化請求 + `time.sleep(0.5)`;這裡是逐層 BFS + 有併發上限的 async 請求。
- 舊版把進度散在 5 個 JSON 快取檔;這裡全部走 `StateStore`,每批寫入包成一個交易,可續傳。
- 舊版把屬性掛在 `time` 模組上(`time.start` / `time.diff`)是 monkey-patch bug;改用
  `time.perf_counter()` 的區域變數。

深度語意沿用舊版:`depth` = 要「展開」的層數。depth=1 只展開種子;depth=2 連種子的外連
條目也展開。最後一層發現的條目仍會成為節點,只是不再往下展開。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .config import PipelineConfig
from .state import StateStore
from .wiki_api import LinksResult, WikiApiError, WikiClient

log = logging.getLogger(__name__)


@dataclass
class CrawlStats:
    expanded: int = 0
    failed: int = 0
    articles: int = 0
    links: int = 0
    elapsed_seconds: float = 0.0


def _record(
    store: StateStore,
    queued_titles: list[str],
    result: LinksResult,
    next_depth: int | None,
) -> None:
    """把一個條目的爬取結果寫進 state store(呼叫端負責包交易)。

    `queued_titles` 是佇列裡指向同一個正式標題的所有寫法(繁簡別名、redirect 來源),
    全部一起結案。
    """
    canonical = result.canonical_title
    for from_title, to_title in result.redirects.items():
        store.add_redirect(from_title, to_title)

    source_idx = store.add_article(canonical)
    links = result.links
    if links:
        target_indices = [store.add_article(t) for t in links]
        store.add_links(source_idx, target_indices)

    for title in queued_titles:
        if title != canonical:
            store.add_redirect(title, canonical)
        store.mark_done(title)
    if canonical not in queued_titles:
        # 正式標題也算做過了,免得下一層又抓一次同一頁
        store.enqueue(canonical, 0)
        store.mark_done(canonical)
    if next_depth is not None and links:
        store.enqueue_many(links, next_depth)


async def _resolve_batch(client: WikiClient, titles: list[str]) -> dict[str, str]:
    """把一批標題收斂成正式標題。MediaWiki 一次最多吃 50 個,超過就自己切。"""
    resolved: dict[str, str] = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i : i + 50]
        try:
            resolved.update(await client.resolve_titles(chunk))
        except (WikiApiError, OSError) as exc:
            # 收斂失敗不該中止整批:退回用原標題,最壞情況只是多一個別名節點
            log.warning("標題收斂失敗(%d 個),沿用原標題:%s", len(chunk), exc)
            resolved.update({t: t for t in chunk})
    return resolved


async def crawl(
    config: PipelineConfig,
    store: StateStore,
    *,
    client: WikiClient | None = None,
    batch_size: int | None = None,
    retry_failed: bool = True,
) -> CrawlStats:
    """執行(或續跑)一次爬取。重跑時只補 `crawl_queue` 裡還沒 done 的條目。"""
    crawl_cfg = config.crawl
    batch = batch_size or crawl_cfg.concurrency * 4
    stats = CrawlStats()
    started = time.perf_counter()

    owns_client = client is None
    client = client or WikiClient(concurrency=crawl_cfg.concurrency)

    store.set_meta("crawl.seeds", crawl_cfg.seeds)
    store.set_meta("crawl.depth", crawl_cfg.depth)
    with store.transaction():
        store.enqueue_many(crawl_cfg.seeds, 0)
        if retry_failed:
            requeued = store.requeue_failed()
            if requeued:
                log.info("把 %d 個上次失敗的條目放回佇列", requeued)

    try:
        for depth in range(crawl_cfg.depth):
            next_depth = depth + 1 if depth + 1 < crawl_cfg.depth else None
            while True:
                titles = store.pending(depth, limit=batch)
                if not titles:
                    break

                # 先把標題收斂到維基的正式標題(解 redirect + 簡繁),避免同一條目被當成兩個節點
                canonical = await _resolve_batch(client, titles)
                # 同一批裡指向同一個正式標題的別名合併,只抓一次
                to_fetch: dict[str, list[str]] = {}
                with store.transaction():
                    for queued, target in canonical.items():
                        if queued != target:
                            store.add_redirect(queued, target)
                        if target != queued and store.is_done(target):
                            # 正式標題已經展開過了,這個別名直接結案
                            store.add_article(target)
                            store.mark_done(queued)
                            continue
                        to_fetch.setdefault(target, []).append(queued)
                if not to_fetch:
                    continue

                batch_items = list(to_fetch.items())
                results = await asyncio.gather(
                    *(client.fetch_links(target) for target, _ in batch_items),
                    return_exceptions=True,
                )
                with store.transaction():
                    for (target, queued_titles), result in zip(batch_items, results, strict=True):
                        if isinstance(result, BaseException):
                            if isinstance(result, (WikiApiError, OSError)):
                                log.warning("爬取 %s 失敗:%s", target, result)
                                for title in queued_titles:
                                    store.mark_failed(title, str(result))
                                stats.failed += 1
                                continue
                            raise result
                        _record(store, queued_titles, result, next_depth)
                        stats.expanded += 1
                log.info(
                    "depth %d:已展開 %d 個條目,累計 %d 節點 / %d 邊",
                    depth,
                    stats.expanded,
                    store.article_count(),
                    store.link_count(),
                )
    finally:
        if owns_client:
            await client.aclose()

    stats.articles = store.article_count()
    stats.links = store.link_count()
    stats.elapsed_seconds = time.perf_counter() - started
    return stats


def export_network_json(store: StateStore, path: Path | str) -> Path:
    """輸出 `wiki_network.json`(維持舊版 Index / Title / Directed_Index 結構)。

    原子寫入:先寫暫存檔再 `os.replace`,取代舊版的 `safe_write_json`,
    避免寫到一半被中斷留下壞掉的 JSON。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"Index": idx, "Title": title, "Directed_Index": store.outgoing(idx)}
        for idx, title in store.iter_articles()
    ]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


async def run_scrape(config: PipelineConfig) -> CrawlStats:
    """CLI 進入點:爬取 + 匯出 JSON。"""
    with StateStore(config.state_dir / "pipeline.sqlite") as store:
        stats = await crawl(config, store)
        export_network_json(store, config.output_dir / "wiki_network.json")
    return stats
