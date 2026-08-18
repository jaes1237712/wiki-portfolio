"""實驗腳本共用的資料載入。

這些腳本是**探索用**的,不是 pipeline 的一部分:不寫入任何東西、沒有測試、
可以隨意改。它們存在的唯一目的是讓 docs/data-strategy.md 裡的數字可以被重跑、
被質疑、被推翻。
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
STATE_DB = PIPELINE_DIR / "state" / "pipeline.sqlite"
OUTPUT_DIR = PIPELINE_DIR / "output"

# 讓 `python experiments/xxx.py` 也 import 得到 wiki_pipeline
sys.path.insert(0, str(PIPELINE_DIR))


@dataclass
class Snapshot:
    """一次爬取的狀態快照。"""

    conn: sqlite3.Connection
    #: idx → 維基正式標題
    raw: dict[int, str]
    #: idx → 台灣繁體顯示標題
    disp: dict[int, str]
    #: 顯示標題 → idx(反查用)
    by_disp: dict[str, int]
    #: 被展開過(問過外連)的 idx —— 只有這些節點的出邊是完整的
    core: set[int]
    #: (source_idx, target_idx)
    edges: list[tuple[int, int]]

    @property
    def core_titles(self) -> set[str]:
        return {self.raw[i] for i in self.core}


def load() -> Snapshot:
    if not STATE_DB.exists():
        raise SystemExit(
            f"找不到 {STATE_DB}\n"
            "先跑:pipeline run-stage scrape && pipeline run-stage extracts"
        )
    conn = sqlite3.connect(STATE_DB)
    raw = {i: t for i, t in conn.execute("select idx,title from articles")}
    disp = {i: d for i, d in conn.execute("select idx,title_display from articles")}
    expanded = {t for (t,) in conn.execute("select title from crawl_queue where status='done'")}
    core = {i for i, t in raw.items() if t in expanded}
    edges = list(conn.execute("select source_idx,target_idx from links"))
    return Snapshot(conn, raw, disp, {d: i for i, d in disp.items()}, core, edges)


def header(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)
