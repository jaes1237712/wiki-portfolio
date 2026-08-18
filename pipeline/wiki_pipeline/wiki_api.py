"""MediaWiki API 客戶端(async、有併發上限、會重試)。

舊版是序列化請求 + `time.sleep(0.1)`,大規模爬取會慢到不可行;這裡改成
`asyncio` + semaphore 控併發,並對 429 / 5xx 做指數退避。
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from types import TracebackType

from urllib.parse import quote

import httpx

from . import config as cfg

# gplnamespace=0 已經把非條目命名空間擋掉了,這裡只是雙保險(API 回傳仍可能夾帶)。
EXCLUDED_PREFIXES = (
    "Category:", "分類:", "Portal:", "門戶:", "Wikipedia:", "維基百科:",
    "File:", "檔案:", "Help:", "幫助:", "Template:", "模板:",
    "User:", "用戶:", "Talk:", "討論:",
)


#: MediaWiki 的 TextExtracts 每個請求最多只回 20 筆 extract —— 實測不管 `exlimit` 給多少
#: 都一樣(一次丟 50 個標題只會拿回 20 筆,其餘靜靜地沒有 extract 欄位,不會報錯)。
EXTRACTS_BATCH_LIMIT = 20


def is_article_title(title: str) -> bool:
    return not title.startswith(EXCLUDED_PREFIXES)


@dataclass
class LinksResult:
    """一個條目的外連結果。"""

    # API 正規化 / 解 redirect 之後的實際標題(可能與查詢用的標題不同)。
    canonical_title: str
    links: list[str] = field(default_factory=list)
    # 這次請求觀察到的 redirect 對應 {from: to}。
    redirects: dict[str, str] = field(default_factory=dict)
    missing: bool = False


class WikiApiError(RuntimeError):
    pass


class WikiClient:
    """MediaWiki `api.php` 的最小可用客戶端。"""

    def __init__(
        self,
        *,
        api_url: str = cfg.WIKI_API_URL,
        user_agent: str = cfg.USER_AGENT,
        concurrency: int = 4,
        timeout: float = 30.0,
        max_retries: int = 4,
        variant: str = cfg.WIKI_VARIANT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_url = api_url
        self.max_retries = max_retries
        self.variant = variant
        self._sem = asyncio.Semaphore(concurrency)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )

    async def __aenter__(self) -> WikiClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # --- 底層請求 ---------------------------------------------------------

    async def _get(self, params: dict[str, object]) -> dict:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            async with self._sem:
                try:
                    resp = await self._client.get(self.api_url, params=params)
                except httpx.HTTPError as exc:  # 連線層錯誤
                    last_error = exc
                else:
                    if resp.status_code == 200:
                        data = resp.json()
                        if "error" in data:
                            raise WikiApiError(str(data["error"].get("info", data["error"])))
                        return data
                    if resp.status_code not in (429, 500, 502, 503, 504):
                        raise WikiApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    last_error = WikiApiError(f"HTTP {resp.status_code}")
            # 指數退避 + 抖動,避免所有 worker 同時重試
            await asyncio.sleep(min(2**attempt, 30) * (0.5 + random.random()))
        raise WikiApiError(f"{self.max_retries} 次重試後仍失敗") from last_error

    # --- 標題正規化 -------------------------------------------------------

    async def resolve_titles(self, titles: list[str]) -> dict[str, str]:
        """把輸入標題對應到維基的正式標題(解 redirect + 簡繁轉換)。

        zh 維基的正式標題簡繁混雜(「圖論」的實際頁面是「图论」),不先收斂就會把
        同一個條目當成兩個節點。`generator=links` 的回應不一定會回報 `converted`,
        所以這裡用一支獨立的批次查詢先問清楚。一次最多 50 個標題。
        """
        if not titles:
            return {}
        if len(titles) > 50:
            raise ValueError("一次最多 50 個標題(MediaWiki API 限制)")

        data = await self._get(
            {
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "titles": "|".join(titles),
                "redirects": 1,
                "converttitles": 1,
                "variant": self.variant,
                "utf8": 1,
            }
        )
        query = data.get("query", {})
        mapping = {t: t for t in titles}
        # normalized → converted → redirects 是 MediaWiki 的處理順序,依序套用
        for key in ("normalized", "converted", "redirects"):
            for item in query.get(key, []) or []:
                for original, current in list(mapping.items()):
                    if current == item["from"]:
                        mapping[original] = item["to"]
        return mapping

    # --- 條目連結 ---------------------------------------------------------

    async def fetch_links(self, title: str) -> LinksResult:
        """取得條目的所有主命名空間外連(自動翻頁、解 redirect)。"""
        params: dict[str, object] = {
            "action": "query",
            "generator": "links",
            "titles": title,
            "format": "json",
            "formatversion": 2,
            "gpllimit": "max",
            "gplnamespace": 0,
            "redirects": 1,
            "converttitles": 1,
            "variant": self.variant,
            "utf8": 1,
        }
        result = LinksResult(canonical_title=title)
        seen: set[str] = set()
        continue_params: dict[str, object] = {}

        while True:
            data = await self._get({**params, **continue_params})
            query = data.get("query", {})

            # normalized / redirects 都會影響「查詢標題」到「實際標題」的對應
            for item in query.get("normalized", []) + (query.get("converted") or []):
                if item.get("from") == result.canonical_title:
                    result.canonical_title = item["to"]
            for item in query.get("redirects", []):
                result.redirects[item["from"]] = item["to"]
                if item.get("from") == result.canonical_title:
                    result.canonical_title = item["to"]

            pages = query.get("pages", [])
            if not pages and "query" not in data:
                # generator 沒有任何結果:條目不存在或沒有外連
                result.missing = "query" not in data
                break

            for page in pages:
                page_title = page.get("title")
                if page.get("missing") or not page_title:
                    continue
                if page_title in seen or not is_article_title(page_title):
                    continue
                seen.add(page_title)
                result.links.append(page_title)

            cont = data.get("continue")
            if not cont:
                break
            continue_params = {k: v for k, v in cont.items() if k != "continue"}
            continue_params["continue"] = cont["continue"]

        return result

    # --- 瀏覽量 -----------------------------------------------------------

    async def fetch_pageviews(
        self, title: str, start: str, end: str, granularity: str = "daily"
    ) -> list[tuple[str, int]]:
        """抓某個條目的瀏覽量歷史,回傳 [(YYYY-MM-DD, views), ...]。

        改寫自舊版 `get_pageviewHistory`,差別:
        - 預設抓「每日」而不是每月(沒有日資料就做不了每日異常偵測)
        - 404 代表這個條目在該期間沒有資料(常見:新條目),回空清單而不是當成錯誤
        - 走與其他請求相同的 semaphore 與退避重試
        """
        path = "/".join(
            [
                cfg.PAGEVIEWS_PROJECT,
                cfg.PAGEVIEWS_ACCESS,
                cfg.PAGEVIEWS_AGENT,
                quote(title.replace(" ", "_"), safe=""),
                granularity,
                start,
                end,
            ]
        )
        url = f"{cfg.PAGEVIEWS_API_URL}/{path}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            async with self._sem:
                try:
                    resp = await self._client.get(url)
                except httpx.HTTPError as exc:
                    last_error = exc
                else:
                    if resp.status_code == 200:
                        return [
                            (
                                f"{item['timestamp'][:4]}-{item['timestamp'][4:6]}-"
                                f"{item['timestamp'][6:8]}",
                                int(item.get("views", 0)),
                            )
                            for item in resp.json().get("items", [])
                        ]
                    if resp.status_code == 404:
                        return []
                    if resp.status_code not in (429, 500, 502, 503, 504):
                        raise WikiApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    last_error = WikiApiError(f"HTTP {resp.status_code}")
            await asyncio.sleep(min(2**attempt, 30) * (0.5 + random.random()))
        raise WikiApiError(f"{self.max_retries} 次重試後仍失敗") from last_error

    # --- 條目簡介 ---------------------------------------------------------

    async def fetch_extracts(self, titles: list[str]) -> dict[str, str]:
        """批次取得條目導言(純文字)。一次最多 `EXTRACTS_BATCH_LIMIT` 個標題。"""
        if not titles:
            return {}
        if len(titles) > EXTRACTS_BATCH_LIMIT:
            raise ValueError(
                f"一次最多 {EXTRACTS_BATCH_LIMIT} 個標題(TextExtracts 限制,"
                "超過的部分不會報錯、只會靜靜地沒有 extract)"
            )

        data = await self._get(
            {
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "titles": "|".join(titles),
                "prop": "extracts",
                "exlimit": EXTRACTS_BATCH_LIMIT,
                "exintro": 1,
                "explaintext": 1,
                "redirects": 1,
                "converttitles": 1,
                "variant": self.variant,
                "utf8": 1,
            }
        )
        query = data.get("query", {})
        # 把 API 回的標題對回呼叫端給的原始標題
        alias: dict[str, str] = {}
        for key in ("normalized", "converted", "redirects"):
            for item in query.get(key, []) or []:
                alias[item["to"]] = alias.get(item["from"], item["from"])

        out: dict[str, str] = {}
        for page in query.get("pages", []):
            if page.get("missing"):
                continue
            title = page.get("title")
            extract = page.get("extract")
            if not title or extract is None:
                continue
            out[alias.get(title, title)] = extract
        return out
