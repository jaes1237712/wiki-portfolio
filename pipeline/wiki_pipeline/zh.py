"""繁簡處理。

zh 維基的**正式標題**是簡繁混雜的(「圖論」的實際頁面是「图论」),而且 API 的
`displaytitle` 實測不會做繁簡轉換。所以:

- 正式標題(`articles.title` / `nodes.title`)是圖的穩定 ID,原樣保留,用來組維基連結。
- 顯示用標題(`title_display`)在 pipeline 端用 OpenCC 轉成台灣繁體,存進資料庫,
  前端直接拿來顯示,不必在瀏覽器端載字典轉換。

用 `s2twp`(簡體 → 台灣繁體 + 台灣用詞):「网络科学」→「網路科學」、「算法」→「演算法」,
與 MediaWiki `variant=zh-tw` 回傳的內文用詞一致,標題與簡介才不會一個「網絡」一個「網路」。
"""

from __future__ import annotations

from functools import lru_cache

OPENCC_CONFIG = "s2twp"


@lru_cache(maxsize=1)
def _converter():
    import opencc

    return opencc.OpenCC(OPENCC_CONFIG)


def to_traditional(text: str) -> str:
    """轉成台灣繁體。已經是繁體的字串轉換後不變(冪等)。"""
    if not text:
        return text
    return _converter().convert(text)
