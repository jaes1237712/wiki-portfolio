"""實驗:這張圖的「封閉度」有多低,以及它怎麼汙染了社群角色指標。

對應 docs/data-strategy.md 第 1 節。

封閉 = 一組節點裡每一個都被展開過(問過外連),所以組內的邊全都知道。
未展開的節點在圖裡出度是 0 —— 不是因為它沒有連結,是因為我們沒去問。

用法:
    python experiments/closure_check.py           # 只讀本機資料
    python experiments/closure_check.py --live    # 額外打真的 API 對照出度
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter

from _common import OUTPUT_DIR, header, load


def main(live: bool = False) -> None:
    snap = load()
    total = len(snap.raw)

    header("1. 封閉度")
    out_deg = Counter(s for s, _ in snap.edges)
    print(f"節點總數                {total:>8,}")
    print(f"邊總數                  {len(snap.edges):>8,}")
    print(f"被展開過(出邊完整)     {len(snap.core):>8,}  ← 封閉度 {100*len(snap.core)/total:.1f}%")
    print(f"只知道『誰指向它』       {total-len(snap.core):>8,}")
    assert len(out_deg) <= len(snap.core), "有節點有出邊卻不在 core 裡,資料不一致"

    header("2. 密度:整張圖 vs 封閉子圖")
    inner = sum(1 for s, t in snap.edges if s in snap.core and t in snap.core)
    print(f"整張圖    {total:>6,} 節點 / {len(snap.edges):>6,} 邊  → 平均出度 {len(snap.edges)/total:>5.1f}")
    print(f"封閉子圖  {len(snap.core):>6,} 節點 / {inner:>6,} 邊  → 平均出度 {inner/len(snap.core):>5.1f}")
    print()
    print("→ 節點數不是主要的品質槓桿,封閉度才是。")

    header("3. 出度 0 但其實是大樞紐的節點")
    in_deg = Counter(t for _, t in snap.edges)
    leaves = sorted(((in_deg[i], i) for i in in_deg if out_deg[i] == 0), reverse=True)
    for cnt, idx in leaves[:6]:
        print(f"   {snap.disp[idx]:<16} 入度 {cnt:>3}   出度 0")

    if live:
        header("4. 對照真實 API(證明『沒有出邊』是我們沒問,不是它沒連結)")
        asyncio.run(_compare_live([snap.disp[i] for _, i in leaves[:3]], out_deg, snap))
    else:
        print("\n(加 --live 會打真的 API 對照這些節點的實際外連數)")

    header("5. 角色指標退化:特殊節點是不是只落在已展開的節點裡")
    summary = OUTPUT_DIR / "communities.json"
    if not summary.exists():
        print(f"找不到 {summary},先跑 pipeline run-stage communities")
        return
    data = json.loads(summary.read_text(encoding="utf-8"))
    hits: Counter = Counter()
    for community in data["communities"]:
        for role, info in community["special_nodes"].items():
            hits[(role, info["idx"] in snap.core)] += 1
    print("角色         已展開   未展開")
    for role in ("hub", "authority", "center", "bridge"):
        print(f"  {role:<10} {hits[(role, True)]:>6}   {hits[(role, False)]:>6}")
    print()
    print("hub 的定義是『指向很多重要節點的節點』。只有已展開的節點有出邊,")
    print("所以 hub 必然是它們之一 —— 這個指標在測『我們有沒有去問過它』,")
    print("而不是在測維基百科的結構。")


async def _compare_live(titles: list[str], out_deg: Counter, snap) -> None:
    from wiki_pipeline.wiki_api import WikiClient

    async with WikiClient(concurrency=3) as client:
        results = await asyncio.gather(
            *(client.fetch_links(t) for t in titles), return_exceptions=True
        )
    for title, result in zip(titles, results):
        if isinstance(result, BaseException):
            print(f"   {title:<16} (抓取失敗:{result})")
            continue
        ours = out_deg[snap.by_disp.get(title, -1)]
        print(f"   {title:<16} 維基百科實際外連 {len(result.links):>4} 條   我們資料庫裡 {ours} 條")


if __name__ == "__main__":
    main(live="--live" in sys.argv)
