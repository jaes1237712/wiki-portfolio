# 探索性實驗腳本

[`docs/data-strategy.md`](../../docs/data-strategy.md) 裡每一個標 **[實測]** 的數字都是這裡跑出來的。
存在 repo 裡的理由:**一個沒辦法被重跑的數字,不能拿來做架構決策。**

這些**不是** pipeline 的一部分:

- 不寫入任何東西(只讀 `state/pipeline.sqlite` 與 `output/`)
- 沒有測試,不進 CI,可以隨意改壞
- 會打真的 Wikipedia API(只有加 `--live` 的時候)

## 用法

```bash
cd pipeline
source .venv/Scripts/activate        # Windows Git Bash

python experiments/closure_check.py                 # 封閉度、角色指標退化
python experiments/closure_check.py --live          # 加上「真實外連數 vs 我們的出度」對照
python experiments/closed_subgraph_communities.py   # 封閉小圖的社群、群內/跨群邊比例
python experiments/topic_boundary.py                # 入度分布(不打 API)
python experiments/topic_boundary.py --live         # 加上指回率、conductance
python experiments/payload_sizes.py                 # 各功能 payload、瀏覽量集中度
```

前置條件:`pipeline run-stage scrape` → `extracts` → `graph` → `communities`
(`payload_sizes.py` 的瀏覽量那段還需要 `run-stage pageviews`)。

## 每個腳本回答什麼問題

| 腳本 | 問題 | 結論(2026-08-19) |
|---|---|---|
| `closure_check.py` | 我們的圖有多完整? | **只有 2.4% 的節點被展開過**,而且 hub/center/bridge 100% 落在那些節點裡 —— 角色指標在測爬蟲軌跡,不是維基百科結構 |
| `closed_subgraph_communities.py` | 「大圖」需要額外爬取嗎? | **不需要**。封閉小圖的跨群邊佔 7%、權重有層次,大圖是小圖的副產品 |
| `topic_boundary.py` | 怎麼判斷一個條目屬不屬於這個主題? | 入度**不能用**(測知名度);指回率對參照集過度敏感;conductance 方向正確但需要迭代 |
| `payload_sizes.py` | 什麼可以一次載完、什麼要 lazy load? | 除了全圖(475 KB gzip),每個功能都是 KB 等級;瀏覽量抽前 10% 涵蓋 68% 流量 |

## ⚠️ 數字會變

維基百科本身會變,而且這些腳本讀的 `state/pipeline.sqlite` 不進版控。
在新裝置上重跑出來的數字**不會**與 `docs/data-strategy.md` 完全一致 ——
那份文件的數字是 2026-08-19 的快照。**結論(排序、量級、方向)應該還成立;
如果連結論都翻了,那是真的發現,要回去改文件。**
