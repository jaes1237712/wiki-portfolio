"""實驗:前端每個功能實際要下載多少,以及瀏覽量的集中度。

對應 docs/data-strategy.md 第 4 節與 5.4 節。

前者決定「哪些資料可以一次載完、哪些要 lazy load」;
後者決定「主題趨勢抽樣多少節點才夠」。

用法:
    python experiments/payload_sizes.py
"""

from __future__ import annotations

import gzip
import json
import random

import igraph as ig

from _common import OUTPUT_DIR, header, load


def sizes(obj) -> tuple[float, float]:
    """回傳 (原始 KB, gzip KB)。"""
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    return len(raw) / 1024, len(gzip.compress(raw, 6)) / 1024


def report(label: str, obj) -> None:
    raw_kb, gz_kb = sizes(obj)
    print(f"  {label:<34} {raw_kb:>8.1f} KB  →  gzip {gz_kb:>7.1f} KB")


def main() -> None:
    snap = load()
    random.seed(1)

    header("前端 payload(節點座標與 pagerank 用模擬值,只影響數量級不影響結論)")
    graph_file = OUTPUT_DIR / "graph.graphml"
    if graph_file.exists():
        graph = ig.Graph.Read_GraphML(str(graph_file))
        idxs = [int(v["idx"]) for v in graph.vs]
        pagerank = graph.pagerank()
        nodes = [
            {
                "i": i, "t": snap.disp.get(i, ""), "c": random.randint(0, 36),
                "r": round(p, 7),
                "x": round(random.random() * 100, 2), "y": round(random.random() * 100, 2),
            }
            for i, p in zip(idxs, pagerank)
        ]
        edges = [
            {
                "s": int(graph.vs[e.source]["idx"]),
                "t": int(graph.vs[e.target]["idx"]),
                "w": round(e["weight"], 4) if "weight" in graph.es.attributes() else 1,
            }
            for e in graph.es
        ]
        report(f"全圖節點({len(nodes):,})", nodes)
        report(f"全圖邊({len(edges):,})", edges)
        report("全圖合計", {"nodes": nodes, "edges": edges})

        # 舊版 topology_view_edges 的裁切法:每個 source 取權重前 3 名
        by_source: dict[int, list] = {}
        for e in graph.es:
            by_source.setdefault(e.source, []).append(e)
        top = sum(len(sorted(es, key=lambda e: -e["weight"])[:3]) for es in by_source.values())
        print(f"\n  舊版裁切法(每 source 前 3 名)→ {top:,} 條邊")
    else:
        print(f"  找不到 {graph_file},先跑 pipeline run-stage graph")

    relation = OUTPUT_DIR / "community_relation.graphml"
    if relation.exists():
        r = ig.Graph.Read_GraphML(str(relation))
        report(
            f"社群關係 meta-graph({r.vcount()}/{r.ecount()})",
            {
                "nodes": [{k: v[k] for k in r.vs.attributes() if k != "id"} for v in r.vs],
                "edges": [
                    {"s": e.source, "t": e.target, **{k: e[k] for k in r.es.attributes()}}
                    for e in r.es
                ],
            },
        )

    subgraphs = sorted((OUTPUT_DIR / "subgraphs").glob("*.graphml"), key=lambda p: -p.stat().st_size)
    if subgraphs:
        s = ig.Graph.Read_GraphML(str(subgraphs[0]))
        report(
            f"最大社群子圖({s.vcount()}/{s.ecount()})",
            {
                "nodes": [{k: v[k] for k in s.vs.attributes() if k != "id"} for v in s.vs],
                "edges": [
                    {"s": e.source, "t": e.target, **{k: e[k] for k in s.es.attributes()}}
                    for e in s.es
                ],
            },
        )

    report(f"搜尋用標題索引({len(snap.disp):,} 筆)", list(snap.disp.items()))

    row = snap.conn.execute(
        "select idx from pageviews group by idx having count(*) >= 300 limit 1"
    ).fetchone()
    if row:
        daily = snap.conn.execute(
            "select date,views from pageviews where idx=? order by date", (row[0],)
        ).fetchall()
        report(f"單節點日瀏覽量({len(daily)} 點)", daily)
        report("單節點半月瀏覽量(25 點)", daily[:25])
    extract = snap.conn.execute(
        "select extract from extracts where extract is not null limit 1"
    ).fetchone()
    if extract:
        report(f"單筆簡介({len(extract[0])} 字)", extract[0])

    header("Neon 儲存:每列的實際大小基礎")
    stats = snap.conn.execute(
        "select count(*), avg(length(extract)), max(length(extract)) "
        "from extracts where extract is not null"
    ).fetchone()
    if stats and stats[0]:
        print(f"  有簡介的條目      {stats[0]:>8,}")
        print(f"  平均長度          {stats[1]:>8.0f} 字 ≈ {stats[1]*3:>5.0f} bytes(UTF-8 中文)")
        print(f"  最長              {stats[2]:>8,} 字")
        print("  → nodes 一列約 1.4 KB(含索引);halfvec(1024) 約 4.2 KB;邊約 80 B")

    header("瀏覽量集中度 → 主題趨勢要抽樣多少節點")
    totals = [v for (v,) in snap.conn.execute(
        "select sum(views) from pageviews group by idx"
    )]
    if not totals:
        print("  還沒有瀏覽量資料,先跑 pipeline run-stage pageviews")
        return
    totals.sort(reverse=True)
    grand = sum(totals)
    print(f"  有瀏覽量的節點 {len(totals):,} 個,期間總量 {grand:,}\n")
    print("  抽樣                          涵蓋總瀏覽量")
    for k in (10, 25, 50, 100, 200, 500, 1000):
        if k > len(totals):
            break
        share = 100 * sum(totals[:k]) / grand
        print(f"    前 {k:>5} 名(節點的 {100*k/len(totals):>5.1f}%)  {share:>10.1f}%")
    print()
    print("  → 抽前 10% 涵蓋約 68% 流量。這個數字要標在頁面上:")
    print("    有標註的抽樣是資料治理,沒標註的才是偷懶。")


if __name__ == "__main__":
    main()
