"""可續傳的 checkpoint store(SQLite)。

取代舊版散落的 5 個 JSON 快取檔(index_mapping / redirect / processed_titles /
article / views cache)。大規模爬取一定會被中斷,所有進度都必須落在這裡,
重跑時只補沒做完的部分。

設計原則:
- 單一檔案、單一連線,寫入用交易包起來,中途 Ctrl-C 不會留下半筆資料。
- 標題一律存「正規化後」(解過 redirect)的標題;redirect 對應另外存一張表。
- idx 由 SQLite AUTOINCREMENT 產生並保證不重用,是之後整條 pipeline 與資料庫的穩定 ID。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from .zh import to_traditional

CrawlStatus = Literal["pending", "done", "failed"]

_SCHEMA = """
-- title 是維基的正式標題(圖的穩定 ID);title_display 是 OpenCC 轉出的台灣繁體顯示標題。
CREATE TABLE IF NOT EXISTS articles (
    idx           INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL UNIQUE,
    title_display TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS links (
    source_idx INTEGER NOT NULL,
    target_idx INTEGER NOT NULL,
    PRIMARY KEY (source_idx, target_idx)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS links_target_idx ON links (target_idx);

-- 爬取佇列:哪些條目要展開、展開到第幾層、做完了沒。續傳就是靠這張表。
CREATE TABLE IF NOT EXISTS crawl_queue (
    title  TEXT PRIMARY KEY,
    depth  INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error  TEXT
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS crawl_queue_status ON crawl_queue (status, depth);

CREATE TABLE IF NOT EXISTS redirects (
    from_title TEXT PRIMARY KEY,
    to_title   TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS extracts (
    idx     INTEGER PRIMARY KEY,
    extract TEXT
);

-- 每日瀏覽量。半月彙總是從這裡算出來的,不另外打 API。
CREATE TABLE IF NOT EXISTS pageviews (
    idx   INTEGER NOT NULL,
    date  TEXT NOT NULL,
    views INTEGER NOT NULL,
    PRIMARY KEY (idx, date)
) WITHOUT ROWID;

-- 每個條目抓過哪一段期間,續傳時才知道誰還沒抓、誰抓失敗。
CREATE TABLE IF NOT EXISTS pageview_status (
    idx        INTEGER PRIMARY KEY,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    status     TEXT NOT NULL,
    error      TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
"""


class StateStore:
    """Pipeline 的續傳狀態。用法:`with StateStore(path) as store: ...`"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- 生命週期 ---------------------------------------------------------

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """一批寫入包成一個交易:中斷時要嘛整批寫進去,要嘛完全沒寫。"""
        try:
            yield self.conn
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    # --- 條目 -------------------------------------------------------------

    def add_article(self, title: str) -> int:
        """回傳條目的 idx;已存在就直接回傳既有的(不會產生新 idx)。"""
        row = self.conn.execute("SELECT idx FROM articles WHERE title = ?", (title,)).fetchone()
        if row is not None:
            return int(row["idx"])
        cur = self.conn.execute(
            "INSERT INTO articles (title, title_display) VALUES (?, ?)",
            (title, to_traditional(title)),
        )
        return int(cur.lastrowid)

    def add_articles(self, titles: Iterable[str]) -> dict[str, int]:
        """批次版本,回傳 {title: idx}。"""
        return {title: self.add_article(title) for title in titles}

    def get_idx(self, title: str) -> int | None:
        row = self.conn.execute("SELECT idx FROM articles WHERE title = ?", (title,)).fetchone()
        return int(row["idx"]) if row else None

    def article_count(self) -> int:
        row = self.conn.execute("SELECT count(*) AS n FROM articles").fetchone()
        return int(row["n"])

    def iter_articles(self) -> Iterator[tuple[int, str]]:
        """(idx, 正式標題)。要顯示標題請用 `iter_articles_full`。"""
        for row in self.conn.execute("SELECT idx, title FROM articles ORDER BY idx"):
            yield int(row["idx"]), str(row["title"])

    def iter_articles_full(self) -> Iterator[tuple[int, str, str]]:
        """(idx, 正式標題, 顯示標題)。"""
        rows = self.conn.execute("SELECT idx, title, title_display FROM articles ORDER BY idx")
        for row in rows:
            yield int(row["idx"]), str(row["title"]), str(row["title_display"])

    def get_display_title(self, title: str) -> str | None:
        row = self.conn.execute(
            "SELECT title_display FROM articles WHERE title = ?", (title,)
        ).fetchone()
        return None if row is None else str(row["title_display"])

    # --- 連結 -------------------------------------------------------------

    def add_links(self, source_idx: int, target_indices: Iterable[int]) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO links (source_idx, target_idx) VALUES (?, ?)",
            ((source_idx, t) for t in target_indices),
        )

    def link_count(self) -> int:
        row = self.conn.execute("SELECT count(*) AS n FROM links").fetchone()
        return int(row["n"])

    def outgoing(self, source_idx: int) -> list[int]:
        rows = self.conn.execute(
            "SELECT target_idx FROM links WHERE source_idx = ? ORDER BY target_idx",
            (source_idx,),
        )
        return [int(r["target_idx"]) for r in rows]

    # --- 爬取佇列 ---------------------------------------------------------

    def enqueue(self, title: str, depth: int) -> None:
        """排入待爬。已經在佇列裡的不動(不會把 done 洗回 pending)。"""
        self.conn.execute(
            "INSERT OR IGNORE INTO crawl_queue (title, depth, status) VALUES (?, ?, 'pending')",
            (title, depth),
        )

    def enqueue_many(self, titles: Iterable[str], depth: int) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO crawl_queue (title, depth, status) VALUES (?, ?, 'pending')",
            ((t, depth) for t in titles),
        )

    def pending(self, depth: int, limit: int | None = None) -> list[str]:
        sql = "SELECT title FROM crawl_queue WHERE status = 'pending' AND depth = ? ORDER BY title"
        params: tuple[object, ...] = (depth,)
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        return [str(r["title"]) for r in self.conn.execute(sql, params)]

    def mark_done(self, title: str) -> None:
        self.conn.execute(
            "UPDATE crawl_queue SET status = 'done', error = NULL WHERE title = ?", (title,)
        )

    def mark_failed(self, title: str, error: str) -> None:
        self.conn.execute(
            "UPDATE crawl_queue SET status = 'failed', error = ? WHERE title = ?", (error, title)
        )

    def requeue_failed(self) -> int:
        """把 failed 的條目放回 pending。續跑時用:失敗多半是暫時性的網路/限流問題。"""
        cur = self.conn.execute(
            "UPDATE crawl_queue SET status = 'pending', error = NULL WHERE status = 'failed'"
        )
        return cur.rowcount

    def status_counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, count(*) AS n FROM crawl_queue GROUP BY status")
        return {str(r["status"]): int(r["n"]) for r in rows}

    def is_done(self, title: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM crawl_queue WHERE title = ? AND status = 'done'", (title,)
        ).fetchone()
        return row is not None

    # --- Redirect ---------------------------------------------------------

    def add_redirect(self, from_title: str, to_title: str) -> None:
        self.conn.execute(
            "INSERT INTO redirects (from_title, to_title) VALUES (?, ?) "
            "ON CONFLICT(from_title) DO UPDATE SET to_title = excluded.to_title",
            (from_title, to_title),
        )

    def resolve(self, title: str) -> str:
        """把 redirect 來源標題收斂到目標標題(最多跟 10 跳,防迴圈)。"""
        seen = {title}
        current = title
        for _ in range(10):
            row = self.conn.execute(
                "SELECT to_title FROM redirects WHERE from_title = ?", (current,)
            ).fetchone()
            if row is None:
                return current
            current = str(row["to_title"])
            if current in seen:
                return current
            seen.add(current)
        return current

    def redirect_count(self) -> int:
        row = self.conn.execute("SELECT count(*) AS n FROM redirects").fetchone()
        return int(row["n"])

    # --- 條目簡介 ---------------------------------------------------------

    def set_extract(self, idx: int, extract: str | None) -> None:
        self.conn.execute(
            "INSERT INTO extracts (idx, extract) VALUES (?, ?) "
            "ON CONFLICT(idx) DO UPDATE SET extract = excluded.extract",
            (idx, extract),
        )

    def get_extract(self, idx: int) -> str | None:
        row = self.conn.execute("SELECT extract FROM extracts WHERE idx = ?", (idx,)).fetchone()
        return None if row is None else row["extract"]

    def missing_extracts(self) -> list[tuple[int, str]]:
        rows = self.conn.execute(
            "SELECT a.idx, a.title FROM articles a "
            "LEFT JOIN extracts e ON e.idx = a.idx WHERE e.idx IS NULL ORDER BY a.idx"
        )
        return [(int(r["idx"]), str(r["title"])) for r in rows]

    # --- 瀏覽量 -----------------------------------------------------------

    def set_pageviews(self, idx: int, points: Iterable[tuple[str, int]]) -> None:
        """寫入某個條目的每日瀏覽量(同日重抓會覆蓋)。"""
        self.conn.executemany(
            "INSERT INTO pageviews (idx, date, views) VALUES (?, ?, ?) "
            "ON CONFLICT(idx, date) DO UPDATE SET views = excluded.views",
            ((idx, date, views) for date, views in points),
        )

    def mark_pageviews_done(self, idx: int, start_date: str, end_date: str) -> None:
        self._set_pageview_status(idx, start_date, end_date, "done", None)

    def mark_pageviews_failed(self, idx: int, start_date: str, end_date: str, error: str) -> None:
        self._set_pageview_status(idx, start_date, end_date, "failed", error)

    def _set_pageview_status(
        self, idx: int, start_date: str, end_date: str, status: str, error: str | None
    ) -> None:
        self.conn.execute(
            "INSERT INTO pageview_status (idx, start_date, end_date, status, error) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(idx) DO UPDATE SET "
            "start_date = excluded.start_date, end_date = excluded.end_date, "
            "status = excluded.status, error = excluded.error",
            (idx, start_date, end_date, status, error),
        )

    def articles_missing_pageviews(
        self, start_date: str, end_date: str, limit: int | None = None
    ) -> list[tuple[int, str]]:
        """還沒抓過這段期間的條目(含上次失敗的,失敗多半是暫時性的)。"""
        sql = (
            "SELECT a.idx, a.title FROM articles a "
            "LEFT JOIN pageview_status s ON s.idx = a.idx "
            "WHERE s.idx IS NULL OR s.status != 'done' "
            "   OR s.start_date > ? OR s.end_date < ? "
            "ORDER BY a.idx"
        )
        params: tuple[object, ...] = (start_date, end_date)
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        return [(int(r["idx"]), str(r["title"])) for r in self.conn.execute(sql, params)]

    def get_pageviews(self, idx: int) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT date, views FROM pageviews WHERE idx = ? ORDER BY date", (idx,)
        )
        return [(str(r["date"]), int(r["views"])) for r in rows]

    def pageview_count(self) -> int:
        row = self.conn.execute("SELECT count(*) AS n FROM pageviews").fetchone()
        return int(row["n"])

    def pageview_status_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, count(*) AS n FROM pageview_status GROUP BY status"
        )
        return {str(r["status"]): int(r["n"]) for r in rows}

    # --- meta -------------------------------------------------------------

    def set_meta(self, key: str, value: object) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    def get_meta(self, key: str, default: object = None) -> object:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])
