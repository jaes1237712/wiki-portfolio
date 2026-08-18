"""實驗:用「已封閉」的節點模擬多主題設計 —— 大圖是不是小圖的副產品?

對應 docs/data-strategy.md 第 2 節。

只留下出邊完整的節點,得到一張真正沒有漏邊的小圖,對它跑社群偵測,
然後量「群內邊 vs 跨群邊」的比例。跨群邊就是 L1/L2 主題地圖的原料 ——
如果它們夠多、權重有層次,大圖就不需要額外爬取。

用法:
    python experiments/closed_subgraph_communities.py
"""

from __future__ import annotations

import random
from collections import Counter

import igraph as ig

from _common import header, load
from wiki_pipeline.communities import DEFAULT_SEED
from wiki_pipeline.weighting import assign_topology_weights


def main() -> None:
    snap = load()
    order = sorted(snap.core)
    pos = {idx: i for i, idx in enumerate(order)}
    inner_edges = [
        (pos[s], pos[t]) for s, t in snap.edges if s in snap.core and t in snap.core
    ]

    graph = ig.Graph(directed=True)
    graph.add_vertices(len(order))
    graph.vs["idx"] = order
    graph.add_edges(inner_edges)
    graph.simplify(multiple=True, loops=True)
    assign_topology_weights(graph)

    # Infomap 是隨機演算法,固定種子才能重現(見 decisions.md #16)
    random.seed(DEFAULT_SEED)
    ig.set_random_number_generator(random.Random(DEFAULT_SEED))
    part = graph.community_infomap(edge_weights=graph.es["weight"], trials=10)

    header("封閉小圖的社群結構")
    print(f"{graph.vcount()} 節點 / {graph.ecount()} 邊 → Infomap 分成 {len(part)} 群")
    print(f"群大小:{sorted(part.sizes(), reverse=True)}")

    header("群內邊 vs 跨群邊(= L1/L2 主題地圖的原料)")
    membership = part.membership
    pair: Counter = Counter()
    inner = 0
    for edge in graph.es:
        a, b = membership[edge.source], membership[edge.target]
        if a == b:
            inner += 1
        else:
            pair[tuple(sorted((a, b)))] += 1
    cross = graph.ecount() - inner
    print(f"群內邊 {inner:,} ({100*inner/graph.ecount():.0f}%)")
    print(f"跨群邊 {cross:,} ({100*cross/graph.ecount():.0f}%)")

    big = [i for i, size in enumerate(part.sizes()) if size >= 10]
    possible = len(big) * (len(big) - 1) // 2
    actual = sum(1 for (a, b) in pair if a in big and b in big)
    print(f"\n≥10 節點的群:{len(big)} 個 → 可能配對 {possible},實際有邊的配對 {actual}")
    print(f"最強的跨群連結權重:{[n for _, n in pair.most_common(8)]}")
    print()
    print("→ 跨群邊本來就在爬取結果裡,目前被丟掉。只要不丟,大圖就是免費的。")

    header("分群的語意檢查(人來判斷合不合理)")
    by_size = sorted(enumerate(part.sizes()), key=lambda x: -x[1])
    for cid, size in by_size[:5]:
        names = [snap.disp[order[i]] for i, m in enumerate(membership) if m == cid][:8]
        print(f"  群{cid:<3}({size:>3} 個):{' / '.join(names)}")

    biggest = by_size[0][1]
    if biggest / graph.vcount() > 0.4:
        print()
        print(f"⚠️ 最大的群佔 {100*biggest/graph.vcount():.0f}% —— 出現巨群。")
        print("   如果每個主題都這樣,L2 子社群地圖就撐不起來(見 data-strategy.md 實驗 2)。")


if __name__ == "__main__":
    main()
