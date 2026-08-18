"""Pipeline CLI:`pipeline run-stage <stage>`。

每個階段都可以單獨執行、可續傳(state store),這樣大規模爬取被中斷時不必從頭來過。
未實作的階段見 docs/roadmap.md 的 Phase 2-4。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging

import typer

from . import config as cfg
from .scrape import run_scrape
from .stages import (
    pageviews_summary,
    run_communities_stage,
    run_extracts_stage,
    run_graph_stage,
    run_pageviews_stage,
)
from .state import StateStore

app = typer.Typer(help="維基百科連結網絡 pipeline", no_args_is_help=True)

STAGES = {
    "scrape": "Phase 1 — 爬取連結圖",
    "extracts": "Phase 1 — 抓條目簡介",
    "pageviews": "Phase 1 — 抓每日瀏覽量",
    "graph": "Phase 2 — 建圖 + 邊權重",
    "communities": "Phase 2 — 兩層社群偵測",
    "embed": "Phase 3 — Workers AI embedding",
    "load": "Phase 4 — 寫入 Neon",
}


def _build_config(seeds: list[str] | None, depth: int | None, concurrency: int | None) -> cfg.PipelineConfig:
    base = cfg.DEV_CONFIG
    crawl = dataclasses.replace(
        base.crawl,
        seeds=seeds or base.crawl.seeds,
        depth=depth or base.crawl.depth,
        concurrency=concurrency or base.crawl.concurrency,
    )
    return dataclasses.replace(base, crawl=crawl)


@app.command("run-stage")
def run_stage(
    stage: str = typer.Argument(..., help=" | ".join(STAGES)),
    seed: list[str] = typer.Option(None, "--seed", help="種子條目(可重複);預設用 DEV_SEEDS"),
    depth: int = typer.Option(None, help="要展開的層數"),
    concurrency: int = typer.Option(None, help="同時發出的請求數上限"),
    limit: int = typer.Option(None, help="只處理前 N 個條目(pageviews 階段試跑用)"),
    verbose: bool = typer.Option(True, help="顯示進度 log"),
) -> None:
    """執行單一階段。"""
    if stage not in STAGES:
        raise typer.BadParameter(f"未知階段 {stage!r};可用:{', '.join(STAGES)}")

    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # httpx 每個請求都會印一行 INFO,大規模爬取時會把真正的進度訊息淹掉
    logging.getLogger("httpx").setLevel(logging.WARNING)
    conf = _build_config(list(seed) if seed else None, depth, concurrency)

    if stage == "scrape":
        stats = asyncio.run(run_scrape(conf))
        typer.echo(
            f"完成:展開 {stats.expanded} 個條目(失敗 {stats.failed}),"
            f"共 {stats.articles} 節點 / {stats.links} 邊,耗時 {stats.elapsed_seconds:.1f} 秒"
        )
        typer.echo(f"輸出:{conf.output_dir / 'wiki_network.json'}")
        return

    if stage == "extracts":
        stats = asyncio.run(run_extracts_stage(conf))
        typer.echo(
            f"完成:{stats.fetched} 個條目有簡介,{stats.missing} 個查不到"
            f"(共處理 {stats.total} 個)"
        )
        return

    if stage == "pageviews":
        stats = asyncio.run(run_pageviews_stage(conf, limit=limit))
        start_date, end_date = conf.pageviews.date_range()
        typer.echo(
            f"完成:{stats.fetched} 個條目有資料、{stats.empty} 個沒有、{stats.failed} 個失敗"
            f"(共 {stats.total} 個),寫入 {stats.rows} 筆日資料({start_date}~{end_date})"
        )
        summary = pageviews_summary(conf)
        typer.echo(f"資料庫累計 {summary['total_daily_rows']} 筆日資料")
        typer.echo(f"輸出:{conf.output_dir / 'pageviews_summary.json'}")
        return

    if stage == "graph":
        graph = run_graph_stage(conf)
        typer.echo(f"完成:{graph.vcount()} 節點 / {graph.ecount()} 邊,已加上拓樸相似度權重")
        typer.echo(f"輸出:{conf.output_dir / 'graph.graphml'}")
        return

    if stage == "communities":
        artifacts = run_communities_stage(conf)
        typer.echo(
            f"完成:{len(artifacts.detection.community_sizes)} 個社群"
            f"(codelength {artifacts.detection.codelength:.4f}),"
            f"其中 {len(artifacts.subgraphs)} 個有效社群"
        )
        typer.echo(
            f"社群關係圖:{artifacts.relation.vcount()} 頂點 / {artifacts.relation.ecount()} 邊"
        )
        typer.echo(f"輸出:{conf.output_dir / 'communities.json'} 等")
        return

    raise NotImplementedError(f"{STAGES[stage]} 尚未實作")


@app.command("status")
def status() -> None:
    """看目前 checkpoint 的進度(可續傳狀態)。"""
    conf = cfg.DEV_CONFIG
    db = conf.state_dir / "pipeline.sqlite"
    if not db.exists():
        typer.echo(f"還沒有 state:{db}")
        raise typer.Exit(code=0)
    with StateStore(db) as store:
        counts = store.status_counts()
        typer.echo(f"state       : {db}")
        typer.echo(f"seeds       : {store.get_meta('crawl.seeds')}")
        typer.echo(f"depth       : {store.get_meta('crawl.depth')}")
        typer.echo(f"queue       : {counts or '(空)'}")
        typer.echo(f"articles    : {store.article_count()}")
        typer.echo(f"links       : {store.link_count()}")
        typer.echo(f"redirects   : {store.redirect_count()}")


@app.command("show-config")
def show_config() -> None:
    """印出目前的開發設定,確認種子/門檻/模型是否符合預期。"""
    conf = cfg.DEV_CONFIG
    typer.echo(f"seeds       : {conf.crawl.seeds}")
    typer.echo(f"depth       : {conf.crawl.depth}")
    typer.echo(f"concurrency : {conf.crawl.concurrency}")
    typer.echo(f"community   : min={conf.community.min_node_num} max={conf.community.max_node_num}")
    typer.echo(f"embedding   : {cfg.EMBEDDING_MODEL} ({cfg.EMBEDDING_DIMENSIONS} 維)")
    typer.echo(f"output dir  : {conf.output_dir}")
    typer.echo(f"state dir   : {conf.state_dir}")


if __name__ == "__main__":
    app()
