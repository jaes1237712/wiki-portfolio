"""Pipeline CLI:`pipeline run-stage <stage>`。

每個階段都可以單獨執行、可續傳(state store),這樣大規模爬取被中斷時不必從頭來過。
目前只有骨架,各階段實作見 docs/roadmap.md 的 Phase 1-4。
"""

from __future__ import annotations

import typer

from . import config as cfg

app = typer.Typer(help="維基百科連結網絡 pipeline", no_args_is_help=True)


@app.command("run-stage")
def run_stage(
    stage: str = typer.Argument(..., help="scrape | graph | communities | embed | load"),
    dev: bool = typer.Option(True, help="使用開發用小型 fixture 種子(DEV_SEEDS)"),
) -> None:
    """執行單一階段。"""
    conf = cfg.DEV_CONFIG if dev else None
    if conf is None:
        raise typer.BadParameter("正式種子設定尚未決定,目前只支援 --dev")

    stages = {
        "scrape": "Phase 1 — 爬取連結圖",
        "graph": "Phase 2 — 建圖 + 邊權重",
        "communities": "Phase 2 — 兩層社群偵測",
        "embed": "Phase 3 — Workers AI embedding",
        "load": "Phase 4 — 寫入 Neon",
    }
    if stage not in stages:
        raise typer.BadParameter(f"未知階段 {stage!r};可用:{', '.join(stages)}")

    raise NotImplementedError(f"{stages[stage]} 尚未實作")


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
