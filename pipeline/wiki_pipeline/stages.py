"""把各階段串起來的執行進入點(CLI 用)。

每個階段都會把中繼產物寫進 `output/`,下一個階段可以直接讀,不必重跑上一階段:

    scrape       → output/wiki_network.json          (Phase 1:連結圖)
    extracts     → state 的 extracts 表               (Phase 1:條目簡介)
    pageviews    → state 的 pageviews 表              (Phase 1:每日瀏覽量)
    graph        → output/graph.graphml              (Phase 2a+2b:建圖 + 邊權重)
    communities  → output/community_relation.graphml (Phase 2c:社群偵測 + 子圖 + 特殊節點)
                   output/subgraphs/community_<id>.graphml
                   output/communities.json

GraphML 沿用舊版當除錯用中繼格式:即使最終資料是進 Postgres,能用 Gephi/igraph 直接打開
一張圖來看,對排查「社群怎麼分成這樣」非常有用。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import igraph as ig

from .communities import (
    CommunityDetection,
    CommunitySubgraph,
    SpecialNodes,
    build_community_relation,
    detect_communities,
    effective_subgraphs,
    mark_special_nodes,
)
from .config import PipelineConfig
from .pageviews import average_pageviews, to_half_month
from .wiki_api import WikiApiError, WikiClient
from .graph_build import build_graph_from_store, load_records, build_graph
from .state import StateStore
from .weighting import assign_topology_weights

log = logging.getLogger(__name__)

GRAPH_FILE = "graph.graphml"
RELATION_FILE = "community_relation.graphml"
SUBGRAPH_DIR = "subgraphs"
SUMMARY_FILE = "communities.json"


@dataclass
class CommunityArtifacts:
    graph: ig.Graph
    detection: CommunityDetection
    subgraphs: list[CommunitySubgraph]
    specials: list[SpecialNodes]
    relation: ig.Graph


def run_graph_stage(config: PipelineConfig) -> ig.Graph:
    """Phase 2a+2b:從 checkpoint(或 wiki_network.json)建圖並算邊權重。"""
    state_db = config.state_dir / "pipeline.sqlite"
    network_json = config.output_dir / "wiki_network.json"

    if state_db.exists():
        with StateStore(state_db) as store:
            graph = build_graph_from_store(store)
    elif network_json.exists():
        graph = build_graph(load_records(network_json))
    else:
        raise FileNotFoundError(f"找不到 {state_db} 或 {network_json},請先跑 run-stage scrape")

    assign_topology_weights(graph)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    graph.write_graphml(str(config.output_dir / GRAPH_FILE))
    return graph


def load_weighted_graph(config: PipelineConfig) -> ig.Graph:
    """讀 graph 階段的產物;沒有的話就當場重建一次。"""
    path = config.output_dir / GRAPH_FILE
    if not path.exists():
        log.info("找不到 %s,先跑 graph 階段", path)
        return run_graph_stage(config)
    graph = ig.Graph.Read_GraphML(str(path))
    # GraphML 會把數值屬性讀成字串以外的型別不一定一致,idx 一律轉回 int
    graph.vs["idx"] = [int(v) for v in graph.vs["idx"]]
    return graph


def run_communities_stage(config: PipelineConfig) -> CommunityArtifacts:
    """Phase 2c:社群偵測 → 有效子圖 → 特殊節點 → 社群關係 meta-graph。"""
    graph = load_weighted_graph(config)
    detection = detect_communities(graph, trials=5)
    subgraphs = effective_subgraphs(graph, config.community)
    specials = mark_special_nodes(graph, subgraphs)
    relation = build_community_relation(graph, specials)

    write_community_artifacts(
        CommunityArtifacts(graph, detection, subgraphs, specials, relation), config.output_dir
    )
    return CommunityArtifacts(graph, detection, subgraphs, specials, relation)


def write_community_artifacts(artifacts: CommunityArtifacts, output_dir: Path) -> list[Path]:
    """寫出 meta-graph、每個社群的子圖,以及一份人看得懂的摘要 JSON。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if artifacts.relation.vcount() > 0:
        relation_path = output_dir / RELATION_FILE
        artifacts.relation.write_graphml(str(relation_path))
        written.append(relation_path)

    subgraph_dir = output_dir / SUBGRAPH_DIR
    subgraph_dir.mkdir(parents=True, exist_ok=True)
    for item in artifacts.subgraphs:
        path = subgraph_dir / f"community_{item.community}.graphml"
        item.graph.write_graphml(str(path))
        written.append(path)

    titles = {int(v["idx"]): v["title_display"] for v in artifacts.graph.vs}
    summary = {
        "codelength": artifacts.detection.codelength,
        "community_count": len(artifacts.detection.community_sizes),
        "effective_community_count": len(artifacts.subgraphs),
        "community_sizes": artifacts.detection.community_sizes,
        "communities": [
            {
                "community": special.community,
                "size": next(
                    s.graph.vcount() for s in artifacts.subgraphs if s.community == special.community
                ),
                "special_nodes": {
                    role: {"idx": idx, "title": titles.get(idx)}
                    for role, idx in special.roles.items()
                },
            }
            for special in artifacts.specials
        ],
    }
    summary_path = output_dir / SUMMARY_FILE
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    written.append(summary_path)
    return written


# --- Phase 1 的其餘階段 -----------------------------------------------------


@dataclass
class ExtractsStats:
    fetched: int = 0
    missing: int = 0
    total: int = 0


async def run_extracts_stage(config: PipelineConfig, batch_size: int = 50) -> ExtractsStats:
    """抓所有條目的導言文字(Phase 3 的 embedding 與前端的詳情面板都要用)。

    可續傳:只抓 `extracts` 表裡還沒有的條目。查不到簡介的條目會寫入 NULL,
    代表「問過了、沒有」,下次不會再問一遍。
    """
    stats = ExtractsStats()
    with StateStore(config.state_dir / "pipeline.sqlite") as store:
        pending = store.missing_extracts()
        stats.total = len(pending)
        if not pending:
            log.info("所有條目都已經有簡介了")
            return stats

        # 每批 50 個標題(API 上限),再讓多批同時飛,否則 13,000 個條目要跑十幾分鐘
        batches = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
        group_size = config.crawl.concurrency
        async with WikiClient(concurrency=config.crawl.concurrency) as client:
            for group_start in range(0, len(batches), group_size):
                group = batches[group_start : group_start + group_size]
                results = await asyncio.gather(
                    *(client.fetch_extracts([title for _, title in batch]) for batch in group),
                    return_exceptions=True,
                )
                with store.transaction():
                    for batch, extracts in zip(group, results, strict=True):
                        if isinstance(extracts, BaseException):
                            if isinstance(extracts, (WikiApiError, OSError)):
                                log.warning("抓簡介失敗(%d 個條目),稍後可續跑:%s", len(batch), extracts)
                                continue
                            raise extracts
                        for idx, title in batch:
                            text = extracts.get(title)
                            store.set_extract(idx, text)
                            if text:
                                stats.fetched += 1
                            else:
                                stats.missing += 1
                done = min((group_start + group_size) * batch_size, len(pending))
                log.info("簡介進度:%d/%d", done, len(pending))
    return stats


@dataclass
class PageviewsStats:
    fetched: int = 0
    empty: int = 0
    failed: int = 0
    rows: int = 0
    total: int = 0


async def run_pageviews_stage(
    config: PipelineConfig, limit: int | None = None, today=None
) -> PageviewsStats:
    """抓每日瀏覽量。可續傳:只抓還沒抓過(或上次失敗)的條目。"""
    start_date, end_date = config.pageviews.date_range(today)
    stats = PageviewsStats()

    with StateStore(config.state_dir / "pipeline.sqlite") as store:
        pending = store.articles_missing_pageviews(start_date, end_date, limit=limit)
        stats.total = len(pending)
        if not pending:
            log.info("所有條目都已經抓過 %s~%s 的瀏覽量了", start_date, end_date)
            return stats
        log.info("要抓 %d 個條目的瀏覽量(%s~%s)", len(pending), start_date, end_date)

        batch_size = config.pageviews.concurrency * 4
        async with WikiClient(concurrency=config.pageviews.concurrency) as client:
            for start in range(0, len(pending), batch_size):
                batch = pending[start : start + batch_size]
                results = await asyncio.gather(
                    *(
                        client.fetch_pageviews(title, start_date, end_date)
                        for _, title in batch
                    ),
                    return_exceptions=True,
                )
                with store.transaction():
                    for (idx, title), result in zip(batch, results, strict=True):
                        if isinstance(result, BaseException):
                            if isinstance(result, (WikiApiError, OSError)):
                                store.mark_pageviews_failed(idx, start_date, end_date, str(result))
                                stats.failed += 1
                                continue
                            raise result
                        if result:
                            store.set_pageviews(idx, result)
                            stats.rows += len(result)
                            stats.fetched += 1
                        else:
                            stats.empty += 1
                        store.mark_pageviews_done(idx, start_date, end_date)
                log.info(
                    "瀏覽量進度:%d/%d(累計 %d 筆日資料)",
                    start + len(batch),
                    len(pending),
                    stats.rows,
                )
    return stats


def pageviews_summary(config: PipelineConfig, sample: int = 5) -> dict:
    """把每日資料彙總成半月 + 平均,寫出 output/pageviews_summary.json 供人工檢查。"""
    with StateStore(config.state_dir / "pipeline.sqlite") as store:
        rows = []
        for idx, _title, display in list(store.iter_articles_full())[:sample]:
            daily = store.get_pageviews(idx)
            rows.append(
                {
                    "idx": idx,
                    "title": display,
                    "days": len(daily),
                    "average": round(average_pageviews(daily), 2),
                    "half_month": to_half_month(daily)[-4:],
                }
            )
        summary = {"total_daily_rows": store.pageview_count(), "sample": rows}

    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "pageviews_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
