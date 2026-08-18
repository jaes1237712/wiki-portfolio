"""Pipeline 的集中設定。

所有可調參數集中在這裡,避免像舊版 data_factory 一樣散落在各檔案的魔術數字。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# --- Embedding ---------------------------------------------------------------
# 必須與 packages/db-schema/src/config.ts 完全一致:
# 離線 passage embedding 與線上 query embedding 用同一個模型才有相同向量空間。
EMBEDDING_MODEL = "@cf/baai/bge-m3"
EMBEDDING_DIMENSIONS = 1024

# --- 維基百科 API ------------------------------------------------------------
WIKI_LANG = "zh"
WIKI_API_URL = f"https://{WIKI_LANG}.wikipedia.org/w/api.php"
# zh 維基的正式標題是簡繁混雜的(例如「圖論」的實際頁面標題是「图论」)。
# variant + converttitles 讓 API 接受繁體輸入、並用繁體回內容;
# 標題本身仍是正式(可能為簡體)標題,那是圖的穩定 ID,顯示用的繁體轉換另外處理。
WIKI_VARIANT = "zh-tw"
PAGEVIEWS_API_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
# 專案代號、訪問類型、代理人:沿用舊版設定(只算真人瀏覽,不含機器人)。
PAGEVIEWS_PROJECT = "zh.wikipedia"
PAGEVIEWS_ACCESS = "all-access"
PAGEVIEWS_AGENT = "user"
# 維基媒體要求可識別的 User-Agent(含聯絡方式),否則可能被限流。
USER_AGENT = os.getenv(
    "WIKI_USER_AGENT",
    "wiki-portfolio/0.1 (https://github.com/; contact via GitHub issues)",
)

# --- 路徑 --------------------------------------------------------------------
PIPELINE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PIPELINE_ROOT / "output"
STATE_DIR = PIPELINE_ROOT / "state"


@dataclass(frozen=True)
class CrawlConfig:
    """一次爬取任務的參數。種子與深度都可參數化,不寫死。"""

    seeds: list[str]
    depth: int = 2
    # 同時發出的請求數上限(舊版是序列化 + time.sleep(0.1),太慢)。
    concurrency: int = 4
    # 每個條目最多取幾條外連(0 = 不限)。
    max_links_per_article: int = 0


@dataclass(frozen=True)
class CommunityConfig:
    """社群偵測與有效子圖過濾參數。

    舊版把 min/max 寫死成 50/500,在小型測試種子的規模下會濾掉「所有」社群,
    所以這兩個值一定要可參數化。
    """

    min_node_num: int = 50
    max_node_num: int = 500
    infomap_args: str = "--two-level --directed --silent"


@dataclass(frozen=True)
class PageviewsConfig:
    """瀏覽量抓取範圍。

    一律抓「每日」資料,半月彙總在本地算(舊版只抓 monthly,拿不到日資料就做不了
    每日異常偵測)。天數直接決定資料量:13,000 個條目 × 365 天 ≈ 475 萬筆。
    """

    days: int = 365
    # Pageviews API 的資料大約落後一天,所以預設不抓到今天。
    lag_days: int = 2
    # 一次同時抓幾個條目。實測:6 個併發跑 100 個條目 0 失敗;開到 12 個併發跑大量條目時
    # 會被限流,約 10% 的條目重試 4 次後仍失敗(續跑時會自動重抓)。
    concurrency: int = 6

    def date_range(self, today: date | None = None) -> tuple[str, str]:
        """回傳 (start, end),格式 YYYYMMDD。"""
        end = (today or date.today()) - timedelta(days=self.lag_days)
        start = end - timedelta(days=self.days - 1)
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


@dataclass(frozen=True)
class PipelineConfig:
    crawl: CrawlConfig
    community: CommunityConfig = field(default_factory=CommunityConfig)
    pageviews: PageviewsConfig = field(default_factory=PageviewsConfig)
    output_dir: Path = OUTPUT_DIR
    state_dir: Path = STATE_DIR


# --- 開發用小型 fixture 種子 --------------------------------------------------
# 不是最終作品集主題,只是讓 Phase 1-6 有東西可以開發、不被「選主題」這個決策卡住。
# 三個都實測存在於 zh 維基(「社群發現」不存在,已換成「複雜網絡」)。
DEV_SEEDS = ["圖論", "網絡科學", "複雜網絡"]

DEV_CONFIG = PipelineConfig(
    crawl=CrawlConfig(seeds=DEV_SEEDS, depth=2, concurrency=4),
    # 小圖的社群一定小於 50 個節點,門檻必須調低才看得到東西。
    community=CommunityConfig(min_node_num=3, max_node_num=200),
)
