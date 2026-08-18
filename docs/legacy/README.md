# 舊專案參考程式碼(唯讀)

這裡是**重寫的參考實作**,不是本專案執行中的程式碼,不要 import、不要修改、不要跑。
放進 repo 只是為了換裝置時還看得到舊邏輯(原始檔在使用者本機 `c:/Users/User/wikiProject/`)。

品質是 prototype 等級,已知有 bug,移植時的注意事項見 [../roadmap.md](../roadmap.md)
的「資料管線階段一覽表」。

## 檔案對照

| 檔案 | 原始位置 | 對應 Phase |
|---|---|---|
| `data_factory/build_data.py` | `wiki/data_factory/build_data.py` | Phase 1(爬蟲、簡介擷取、瀏覽量) |
| `data_factory/analyze.py` | `wiki/data_factory/analyze.py` | Phase 2(建圖、權重、社群偵測) |
| `data_factory/get_tag.py` | `wiki/data_factory/get_tag.py` | v1 範圍外(Wikidata 標籤) |
| `web_wiki/schema.ts` | `web_wiki/drizzle/schema.ts` | 已改編進 `packages/db-schema` |
| `web_wiki/analysis.py` | `web_wiki/src/lib/server/python_api/analysis.py` | Phase 5(要移植成 TS) |
| `web_wiki/vector.py` | `web_wiki/src/lib/server/python_api/vector.py` | Phase 5(向量搜尋 SQL) |
| `web_wiki/two_level_community_relation.svelte` | `web_wiki/src/routes/two_level_community_relation/+page.svelte` | Phase 6(互動參考,不移植渲染邏輯) |

## 已知的坑

- `analyze.py` 的 `graph_utils` 不是外部模組,是同檔 730 行的 class;
  `get_similarity_topology` 在 968 行(**非對稱**相似度:`|common| / |neighbors2|`,移植時保留原行為)。
- `build_data.py` 把屬性直接掛在 `time` 模組上(`time.start` / `time.end` / `time.diff`),
  是 monkey-patch bug,重寫時改用區域變數 / `time.perf_counter()`。
- `analyze.py` 的多層社群子圖(`config_G_list_multi_level_subgraphs`)是壞的,**不移植**。
- `vector.py` 第 17 行原本有寫死的本機 DB 連線字串(含密碼),**複製進來時已塗掉**。
- `vector.py` 的 `top_k` 參數被忽略、SQL 寫死 `LIMIT 50`,重寫時要修。
- `build_data.py` 的 `get_articles_extracts` 用 `batch_size=50` 抓導言,但 MediaWiki 的
  TextExtracts **每個請求最多只回 20 筆**(不管 `exlimit` 給多少),超過的部分不會報錯、
  只是靜靜地沒有 extract 欄位 —— 也就是說舊版有 60% 的條目根本沒抓到簡介。新版批次改成 20。
