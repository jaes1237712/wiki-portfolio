"""實驗:哪個指標能判斷「這個候選條目屬於這個主題嗎」?

對應 docs/data-strategy.md 第 3 節。三個候選指標,結論是前兩個都不能用:

    入度        測的是「知名度」不是「主題歸屬」 → 失敗
    指回率      比較好,但對參照集大小過度敏感   → 不能當單一門檻
    conductance 用度數 normalize,方向正確       → 但需要迭代

用法:
    python experiments/topic_boundary.py           # 只讀本機資料(入度分布)
    python experiments/topic_boundary.py --live    # 加上指回率與 conductance(要打 API)
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

from _common import header, load

#: 手挑的測試條目,故意混了「泛稱但入度高」與「專業但入度低」兩種。
#: 前 6 個應該被拒絕,後 6 個應該被收錄 —— 用來看指標的方向對不對。
PROBES = [
    "維基百科", "政治學", "經濟學", "物理學", "國家科學基金會", "勒內·笛卡兒",
    "庫克-李文定理", "子集和問題", "揹包問題", "匹配 (圖論)", "滲流理論", "中心極限定理",
]


def candidate_in_degree(snap) -> Counter:
    """候選節點的入度 = 有多少個已展開節點指向它。"""
    in_deg: Counter = Counter()
    for source, target in snap.edges:
        if source in snap.core and target not in snap.core:
            in_deg[target] += 1
    return in_deg


def main(live: bool = False) -> None:
    snap = load()
    in_deg = candidate_in_degree(snap)

    header("指標一:入度 —— 分布")
    print(f"候選節點(從 {len(snap.core)} 個已展開節點看出去)共 {len(in_deg):,} 個\n")
    print("入度門檻    通過的候選數    佔比")
    for k in (1, 2, 3, 5, 8, 12, 20, 30):
        n = sum(1 for v in in_deg.values() if v >= k)
        print(f"  >= {k:<3}      {n:>8,}      {100*n/len(in_deg):>5.1f}%")

    header("指標一:入度 —— 質性檢查(這裡就看得出它不能用)")
    for low, high in ((1, 1), (2, 2), (3, 4), (5, 7), (8, 15), (20, 99)):
        names = [snap.disp[i] for i, v in in_deg.most_common() if low <= v <= high][:9]
        label = f"{low}" if low == high else f"{low}-{high}"
        print(f"入度 {label:<6} → {' / '.join(names)}")
    print()
    print("入度 1 是核心主題(庫克-李文定理、揹包問題),入度 3-4 是維基百科、")
    print("入度 20+ 是物理學/經濟學。入度測的是知名度,方向剛好是反的。不要用。")

    if not live:
        print("\n(加 --live 會測指回率與 conductance,需要打 API 抓 12 個條目的外連)")
        return

    asyncio.run(_live_metrics(snap, in_deg))


async def _live_metrics(snap, in_deg: Counter) -> None:
    from wiki_pipeline.wiki_api import WikiClient

    core_titles = snap.core_titles
    pool_titles = set(snap.raw.values())

    async with WikiClient(concurrency=6) as client:
        results = await asyncio.gather(
            *(client.fetch_links(t) for t in PROBES), return_exceptions=True
        )

    rows = []
    for title, result in zip(PROBES, results):
        if isinstance(result, BaseException):
            print(f"⚠️ {title} 抓取失敗:{result}")
            continue
        links = result.links
        back_core = sum(1 for l in links if l in core_titles)
        back_pool = sum(1 for l in links if l in pool_titles)
        rows.append((title, len(links), back_core, back_pool))

    header("指標二:指回率 —— 換參照集就翻盤")
    print("對候選池   對核心    指回池/核心/總外連   條目")
    for title, n, bc, bp in sorted(rows, key=lambda r: -r[3] / max(r[1], 1)):
        d = max(n, 1)
        print(f"  {100*bp/d:>5.1f}%   {100*bc/d:>5.1f}%    {bp:>4} /{bc:>4} /{n:>5}   {title}")
    print()
    print("參照集太小 → 專業條目變孤島(庫克-李文定理 4.8%)")
    print("參照集太大 → 什麼都算相關(維基百科 50%)")
    print("絕對的指回率不能當單一門檻。")

    header("指標三:conductance —— 用度數 normalize")
    inner = sum(1 for s, t in snap.edges if s in snap.core and t in snap.core)
    cut = len(snap.edges) - inner
    vol = inner * 2 + cut
    phi = cut / vol
    print(f"目前核心 S({len(snap.core)} 節點)φ = {phi:.5f}\n")
    print("Δφ(負 = 加進來讓主題更凝聚)      指回/外連   條目")
    deltas = []
    for title, n, bc, _bp in rows:
        new_phi = (cut + n - 2 * bc) / (vol + n)
        deltas.append((new_phi - phi, bc, n, title))
    for delta, bc, n, title in sorted(deltas):
        mark = "✓ 收錄" if delta < 0 else "✗ 拒絕"
        print(f"  {delta:+.5f}   {mark}     {bc:>3} /{n:>4}   {title}")
    print()
    print("泛稱條目被斬得很乾淨(維基百科比邊界案例差 50 倍),但假陰性仍在")
    print("(庫克-李文定理、滲流理論)—— 原因是它們的鄰居還沒被收錄,需要迭代。")
    print()
    print("⚠️ 不要對 Δφ 設閾值:絕對值只有 0.0001 量級,訊號在排序不在大小。")
    print("   正確做法是 PPR 排序 + sweep 取 φ 最小的那一刀(見 data-strategy.md 3.4)。")


if __name__ == "__main__":
    main(live="--live" in sys.argv)
