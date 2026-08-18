# 決策紀錄

新決策往下加,不要改寫舊的(要推翻就新增一條寫「取代 #N」)。

## 已定案

### 1. 資料庫用 Neon,不用 Firebase
Cloudflare Workers 沒有原生 TCP socket,Neon 有 HTTP driver(`@neondatabase/serverless`)可直接在
Worker 裡用。Firestore 的 NoSQL 模型也做不到這個專案需要的「關聯查詢 + 向量相似度」。

### 2. 後端用 Cloudflare Workers + Hono
沿用使用者既有的 Cloudflare 部署經驗;與前端 Pages 分開部署,未來行動端可共用同一套 API。

### 3. 前端用 React(Vite SPA),不用 Svelte/Next.js
理由是對 AI coding 工具最友善、可參考知名開源專案的互動模式、為未來行動 App 鋪路。
不用 Next.js 是因為這個專案不需要 SSR,SPA + Pages 部署最單純。

### 4. 圖視覺化用 Sigma.js + graphology,不用 Cytoscape
舊專案用 Cytoscape,文件太少、開發體驗差。Sigma.js 定位是「嚴謹的網絡分析工具」,與本專案的
社群偵測/中心性分析深度相符,WebGL 渲染也撐得住大圖。

### 5. Monorepo 用 npm workspaces
不用 pnpm(使用者明確不想踩奇怪的 bug),不用 yarn。

### 6. 排程拆成兩種
- 輕量每日(抓最新瀏覽量、更新彙總、跑異常偵測)→ Cloudflare Cron Trigger,純 API + 算術,吃得下。
- 重量週期(重爬 + 社群偵測 + embedding)→ GitHub Actions。Workers 是 V8 isolate,沒有 Python
  runtime,igraph/Infomap 根本跑不動,CPU 時間也不夠。

### 7. Embedding 模型暫定 `@cf/baai/bge-m3`(1024 維)
Workers AI 上的多語系模型,涵蓋中文;維度剛好與舊 schema 的 `vector(1024)` 一致。
**離線 pipeline 與線上 Worker 必須用同一個模型**,否則向量空間不相容。
定義在 `packages/db-schema/src/config.ts` 與 `pipeline/wiki_pipeline/config.py`,兩處要一致。
→ 仍待使用者最終確認(見「待決事項」)。

### 8. Schema 相對舊版的取捨
- 表名去掉繪圖庫綁定:`topology_relation_cytoscape_nodes/edges` → `topology_view_nodes/edges`;
  `topology_relation_graph_*` → `topology_*`;`topology_subgraph_*` → `community_subgraph_*`。
- **捨棄** `nodes_query_vector`:查詢 embedding 由 Worker 即時呼叫 Workers AI 產生,不需預存。
- **捨棄** `vector_relation_graph_nodes/edges`、`vector_graph_edges`、
  `subgraph_edges_cosine_similarity`、無型別的舊 `subgraph_edges`:v1 功能清單裡沒有
  「向量相似度圖」這個視圖,先不做。日後要加再開新表。
- **新增** `community_special_nodes`:舊 schema 沒地方存 hub/authority/betweenness/bridge 標記,
  但社群子圖 UI 需要。
- 所有 `bigint` 改成 `integer`:節點數不可能超過 21 億,`bigint` 在 JS 端只會製造麻煩。
- 全面補上主鍵與外鍵(舊版很多表連主鍵都沒有,會產生重複資料)。

### 9. 開發用小型 fixture 種子
`DEV_SEEDS = ["圖論", "網絡科學", "社群發現"]`、depth 2。這不是最終作品集主題,只是讓
Phase 1-6 有東西可開發,不被主題決策卡住。社群過濾門檻在 dev 設定裡調成 min=3/max=200
(舊版寫死 50/500,小圖會濾光所有社群)。

## 待決事項

| # | 待決 | 何時需要 | 現況 |
|---|---|---|---|
| A | 真實爬取的種子主題/領域 | Phase 8 前 | 先用 DEV_SEEDS 開發 |
| B | Embedding 模型最終確認 | Phase 3 前 | 暫定 bge-m3(1024 維) |
| C | 舊專案參考檔案要不要複製進 repo(方便跨裝置參考,但會把 prototype 程式碼放進可能公開的 repo) | 換裝置前 | 未決,目前留在 repo 外 |
| D | GitHub repo 要公開還是私有 | 推上去前 | 未決(公開才有免費無上限的 Actions 分鐘數) |
| E | 首頁是否放個人聯絡資訊 | Phase 11 | 未決 |
| F | 是否要做 Wikidata 標籤功能 | v1 之後 | 目前排除在 v1 外 |
