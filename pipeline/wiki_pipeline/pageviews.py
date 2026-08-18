"""瀏覽量的本地彙總。

只跟維基媒體要「每日」資料,半月彙總與平均值都在本地算 —— 一來少打一輪 API,
二來保證兩種粒度的數字一定對得起來(舊版只抓 monthly,連每日異常偵測都做不了)。

半月的定義:每月 1-15 日算一期(標成該月 01),16 日到月底算一期(標成該月 16)。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

#: 半月分界:16 號(含)以後算下半月。
HALF_MONTH_SPLIT_DAY = 16


def half_month_key(date_str: str) -> str:
    """`2026-08-18` → `2026-08-16`(下半月);`2026-08-03` → `2026-08-01`(上半月)。"""
    year_month, day = date_str[:7], int(date_str[8:10])
    return f"{year_month}-{'16' if day >= HALF_MONTH_SPLIT_DAY else '01'}"


def to_half_month(points: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    """把每日瀏覽量彙總成半月(同一期加總),依日期排序。"""
    totals: dict[str, int] = defaultdict(int)
    for date_str, views in points:
        totals[half_month_key(date_str)] += views
    return sorted(totals.items())


def average_pageviews(points: Sequence[tuple[str, int]]) -> float:
    """期間內的每日平均瀏覽量(沒有資料回 0)。"""
    if not points:
        return 0.0
    return sum(views for _, views in points) / len(points)


def to_community_daily(
    community_of: dict[int, int], pageviews_of: dict[int, Sequence[tuple[str, int]]]
) -> dict[int, list[tuple[str, int]]]:
    """把節點的每日瀏覽量加總成「社群的每日瀏覽量」。

    `community_of`: 條目 idx → 社群編號;`pageviews_of`: 條目 idx → 每日資料。
    """
    totals: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for idx, points in pageviews_of.items():
        community = community_of.get(idx)
        if community is None:
            continue
        for date_str, views in points:
            totals[community][date_str] += views
    return {community: sorted(days.items()) for community, days in totals.items()}
