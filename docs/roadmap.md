# 維基百科知識圖譜作品集 — 重構計畫

## Context

`c:/Users/User/wikiProject` 底下有兩個舊專案:`wiki/`(早期版本,含唯一一份資料管線邏輯 `data_factory/`)與 `web_wiki/`(較成熟的 SvelteKit + FastAPI + Postgres/pgvector 版本,功能完整但程式碼是 prototype 等級)。目標是把這兩份舊專案的價值(資料工程 pipeline 邏輯 + 已驗證可行的功能/資料模型)萃取出來,做一次乾淨的重寫,上架成一個可以展示全端能力的作品集網站。

確認過的關鍵事實:
- `wiki/backend`、`wiki/frontend` 幾乎是空殼或被取代,**整個捨棄**。
- `wiki/data_factory` 是唯一存在的「爬蟲 + 圖論分析」邏輯,是重寫時的參考實作,但有幾處確認壞掉/未完成(多層社群子圖匯出、graphml→json 轉換器是空函式、Wikidata 標籤腳本沒接進主流程、embedding 生成從未真正被呼叫)。
- `web_wiki` 的 Drizzle schema 與 API 設計是有效的參考,但 UI 程式碼(Cytoscape 渲染、GSAP 拖曳版面)品質粗糙,不直接沿用。
- **本機沒有任何已爬取的資料**——Wikipedia 連結圖、社群偵測結果、embedding 全部要從零重新產生。種子主題尚未決定,pipeline 需支援可參數化的種子條目 + 爬取深度。

## 已定案的技術棧決策

| 層面 | 選擇 | 原因 |
|---|---|---|
| 資料管線 | Python,離線批次(非常駐服務) | 沿用 igraph/Infomap,不適合搬進 edge runtime |
| 資料庫 | Neon(Postgres + pgvector) | 有 HTTP driver 相容 Cloudflare Workers(無原生 TCP socket);取代原本的 Firebase 構想 |
| 後端 | Cloudflare Workers(Hono) | 沿用使用者既有的 Cloudflare 部署經驗 |
| 即時 Embedding | Cloudflare Workers AI | 取代自架 Python/torch 微服務;離線 pipeline 產生的 passage embedding 必須用同一個模型,否則向量空間不相容 |
| 前端 | React(Vite SPA,非 Next.js)→ Cloudflare Pages | 對 AI coding 工具最友善、可參考知名專案的互動模式、為未來行動 App 鋪路;與 API 分離部署,方便日後行動端共用同一套 API |
| 圖論視覺化 | Sigma.js + graphology(react-sigma) | 定位為「嚴謹的網絡分析工具」,與本專案的社群偵測/中心性分析深度相符 |
| 圖表 | Recharts | React 宣告式元件模型,`ComposedChart`/`ReferenceDot`/`Brush` 剛好對應「實際值+趨勢線疊圖」「異常點標記」「日期區間篩選」三個需求,比包一層 Chart.js 更貼合 React |
| 排程重算 | 見下方「排程架構」章節 | 拆成輕量(Cloudflare Cron)與重量(GitHub Actions)兩種 |

## Monorepo 結構

```
wiki-portfolio/                      # 新 repo,npm workspaces(package.json 的 "workspaces" 欄位)
├── apps/
│   ├── web/                         # Vite + React SPA → Cloudflare Pages
│   │   └── src/
│   │       ├── routes/              # landing, /graph, /search, /anomalies
│   │       ├── components/graph/    # Sigma.js + graphology 封裝
│   │       ├── components/charts/   # Recharts 封裝
│   │       └── lib/api-client.ts
│   └── api/                         # Cloudflare Worker(Hono)
│       └── src/
│           ├── index.ts             # Hono app、路由註冊、限制來源的 CORS
│           ├── routes/{topology,node,search,analysis}.ts
│           ├── lib/analysis.ts      # 純函式:anomaly_detection、linear_regression(TS 版)
│           ├── lib/db.ts            # @neondatabase/serverless client
│           ├── lib/embeddings.ts    # Workers AI binding
│           └── scheduled.ts         # Cron Trigger handler(輕量 pageviews 更新)
├── packages/
│   ├── shared-types/                 # NodeGraph/EdgeGraph/PageviewsData/SearchResult/AnomalyResult
│   └── db-schema/                    # Drizzle schema(改編自 web_wiki/drizzle/schema.ts,重新命名 Cytoscape 專屬命名)
├── pipeline/                         # Python 離線批次 pipeline(data_factory 重寫)
│   ├── wiki_pipeline/
│   │   ├── scrape.py                # 改寫自 build_data.py: WikiNetworkBuilder
│   │   ├── graph_build.py           # 改寫自 analyze.py: WikiNetwork.create_network
│   │   ├── weighting.py             # 改寫自 config_weight_topology / get_similarity_topology
│   │   ├── communities.py           # 改寫自 config_infomap、special nodes、relation meta-graph
│   │   ├── embeddings.py            # 全新:呼叫 Cloudflare Workers AI
│   │   ├── load_neon.py             # 全新:寫入/upsert 到 Neon
│   │   ├── state.py                 # 全新:單一可續傳的 checkpoint store(取代原本散落的 5 個快取檔)
│   │   └── cli.py                   # `pipeline run-stage scrape|graph|communities|embed|load`
│   ├── tests/
│   └── pyproject.toml
├── .github/workflows/
│   └── recompute.yml                # 全新:排程觸發重量計算 pipeline
└── docs/
```

## Phase 分解(依相依順序)

### Phase 0 — Repo 與 schema 骨架
建立 npm workspaces(根 `package.json` 的 `"workspaces"` 欄位指向 `apps/*`、`packages/*`)、`packages/shared-types`、`packages/db-schema`(改編自 `web_wiki/drizzle/schema.ts`,把 `topology_relation_cytoscape_nodes/edges` 等命名改成與繪圖庫無關的名稱,例如 `topology_relation_view_nodes/edges`)。開一個 Neon 專案 + `dev` branch。固定一組 2-3 篇條目的小型測試種子(非使用者最終主題,只是開發用 fixture),讓 Phase 1-6 都基於它開發,不卡在主題決策上。

### Phase 1 — Pipeline:爬蟲 + 原始連結圖(小型測試種子)
改寫 `build_data.py` 的 `get_article_links`/`add_article`/`process_article`/`build_network`/`safe_write_json`。修正原本 `time.start`/`time.end`/`time.diff` 這種直接把屬性掛在 `time` 模組上的 bug,改用區域變數/`time.perf_counter()`。把原本散落的 5 個快取檔(`index_mapping_cache.json`、`redirect_cache.json`、`processed_titles_cache.json`、`article_cache.json`、`views_cache.json`)整合成 `pipeline/wiki_pipeline/state.py` 單一可續傳的 checkpoint store(例如 SQLite)。輸出:`output/wiki_network.json`(維持 Index/Title/Directed_Index 結構)。

### Phase 2 — Pipeline:圖建構 + 邊權重 + 社群偵測(小型測試種子)
改寫 `WikiNetwork.create_network`/`_load_network`、`config_weight_topology`/`graph_utils.get_similarity_topology`、`config_infomap`、`config_G_list_two_level_effective_subgraphs`、`config_two_level_special_nodes`、`config_G_two_level_community_relation`。

**明確決定:捨棄多層(multi-level)社群子圖功能。** 已確認 `config_G_list_multi_level_subgraphs`(analyze.py 693-729 行)只在 level 1 迴圈裡算出 `subgraph` 就丟棄,從未指派給 `wiki.G_list_multi_level_1_subgraphs`,level 2/3 更是完全沒有程式碼路徑。既然唯一確認可用的參考 UI(`two_level_community_relation`)只用到兩層社群,就只移植兩層版本。

`min_node_num`/`max_node_num`(預設 50-500)的過濾閾值在小型測試種子規模下會濾掉所有社群,需要參數化並在測試情境下調低。

### Phase 3 — Pipeline:Embedding(全新階段)
舊版 `analyze.py` import 了 `SentenceTransformer` 但從未呼叫——這階段完全要重新寫。改用 Cloudflare Workers AI 的 REST embedding endpoint(而非本地 `transformers`/`sentence-transformers`),因為查詢與段落 embedding 必須共用同一個模型/向量空間,唯一能保證這件事的方法就是離線 pipeline 與線上 Worker 呼叫同一個 Workers AI 模型。現在就要選定模型(例如 `@cf/baai/bge-*` 系列)並記錄輸出維度——這會直接決定 `packages/db-schema` 裡 `vector(dimensions)` 欄位寬度(舊 schema 寫死 1024 對應 `multilingual-e5-large-instruct`,新模型維度很可能不同)。文字來源沿用 `build_data.py` 的 `get_articles_extracts`。

### Phase 4 — Pipeline:匯出/寫入 Neon(小型測試種子)— **里程碑**
全新階段,舊 repo 完全沒有寫入 Postgres 的程式碼。批次寫入:`nodes`、`pageviews`(每日)+ 半月彙總、`topology_relation_graph_nodes/edges`、`nodes_passage_vector`、重新命名後的彙總 view。同時預先計算 `anomaly_pageviews`(全資料集的 z-score 表,邏輯與 `analysis.py::anomaly_detection` 相同)作為 **pipeline 端的批次工作**,與 Phase 5 Worker 提供的「即時互動式」異常偵測是不同用途(一個是預先算好的瀏覽表,一個是使用者互動選取範圍時的即時計算)。

**這是解鎖前後端平行開發的里程碑**——一旦 Neon `dev` 裡有真實(即使很小)的資料,Phase 5 與 Phase 6 就能各自獨立開始。

### Phase 5 — 後端 Worker(與 Phase 6 平行)
Hono app,`@neondatabase/serverless`。把舊版分散在 SvelteKit routes 與 FastAPI 微服務的端點整合進同一個 Worker:拓樸圖節點/邊、社群子圖、節點內容、瀏覽量(日/半月)、異常表(分頁/排序,修正舊版忽略 limit 參數的問題)、即時異常偵測與線性回歸(TS 重寫版)、向量搜尋(修正舊版 `top_k` 參數被忽略、SQL 寫死 `LIMIT 50` 的 bug)。從一開始就修正安全問題:限制來源的 CORS(舊版 `allow_origins=["*"]`)、密鑰一律走 Wrangler secrets(舊版 `main.py` 有寫死的 DB 密碼 fallback,絕不重蹈覆轍)。

### Phase 6 — 前端 React app(與 Phase 5 平行)
Sigma.js + graphology 的完整拓樸圖元件(節點大小依 pagerank、依社群著色、點擊高亮鄰居)——寫成一個可重用的 `<TopologyGraph>` 元件,不要像舊版一樣複製兩份幾乎相同的渲染邏輯。社群子圖(依 betweenness 加權)、節點詳情面板(日期區間瀏覽量圖 + 條目簡介)、社群彙總瀏覽量圖、向量搜尋 UI(繁體中文)、異常偵測分頁表格。

**版面決定:不移植 GSAP 可拖曳四欄版面**(舊版確認有 25 處 GSAP/draggable 相關程式碼,且是桌面限定、本來就是較粗糙的部分)。改用響應式版面(CSS Grid + container queries):圖為主畫面,詳情/搜尋/異常面板在手機上是分頁條、桌面上是固定側欄——這也呼應選擇 React 部分原因是為了未來行動端鋪路。

### Phase 7 — 小型資料集整合測試
前端接上真實(非 mock)Worker,手動走過 Phase 6 列出的每個功能,加上全新的 Playwright 煙霧測試(舊版 `wiki/frontend/svelte-app/e2e` 從未接到能動的 UI,沒有可移植的東西)。

### Phase 8 — 全規模 pipeline 執行(使用者選定的真實主題)
使用者決定種子主題/深度後,用已經加固過的 pipeline(checkpoint 機制在這階段才真正派上用場——大規模爬取一定會被中斷)重跑 Phase 1-4。把原本序列化的 `time.sleep(0.1)` 請求模式換成有併發上限的 async 請求。寫入 Neon 的 `production`/`main` branch(與 `dev` 分開)。

### Phase 9 — 部署
Cloudflare Pages(web)+ Workers(api)正式部署,Wrangler secrets 存 Neon 連線字串與 Workers AI binding。效能檢查:拓樸圖 payload 大小(可能需要沿用舊版「top-N + 其餘打包」的邊數量裁切技巧)、`nodes_passage_vector` 的 HNSW 查詢延遲。

### Phase 10 — 排程重算架構

拆成兩個獨立、計算量級完全不同的排程任務:

**A. 輕量每日更新 — Cloudflare Cron Trigger**
在 `apps/api/src/scheduled.ts` 裡用 `wrangler.toml` 的 cron schedule(例如每日一次)。呼叫維基百科 pageviews API 抓現有節點的最新瀏覽量,寫入 `pageviews`、更新 `pageviews_half_month` 與 `nodes.average_pageviews`。重用 Phase 5 已經寫好的 TS 版 `anomaly_detection` 純函式,對新資料視窗重跑並附加進 `anomaly_pageviews`。純 API 呼叫 + 算術運算,完全在 Workers CPU 時間限制內。

**B. 重量週期性重算 — GitHub Actions 排程 workflow**
`.github/workflows/recompute.yml`,例如每週跑一次。**絕不放 Cloudflare Workers**——Workers 是 V8 isolate,沒有 Python runtime,igraph/Infomap 這類原生依賴完全跑不動,即使能跑,CPU 時間限制也會在處理大圖時被中斷。流程:checkout → 安裝 pipeline 依賴 → 用 checkpoint state 判斷「哪些條目是新的/有變化的」→ 只對這些條目重新爬取連結、重建圖、重跑社群偵測、重新產生 embedding(呼叫 Workers AI,與 Phase 3 相同)→ 用 upsert(而非 insert)寫回 Neon。用的是 Phase 1-4 已經寫好的同一套 pipeline 程式碼,差別只在於排程觸發 + 增量處理 + upsert。

選 GitHub Actions 而非其他平台的原因:若 repo 公開(作品集本來就適合公開),GitHub Actions 分鐘數完全免費且無上限;YAML 語法主流、文件齊全;不需要再多學/多付費一個新平台。若之後運算量成長到需要 GPU 或更彈性的資源調度(例如 embedding 數量暴增),可以評估換成 Modal.com(Python 原生的 serverless 排程平台),但現階段規模用 GitHub Actions 就足夠。

### Phase 11 — 作品集包裝
`web_wiki` 的根路由 `+page.svelte` 確認是空的——完全沒有首頁。新首頁(`apps/web` 的 `/`)至少要包含:
1. **Hero**:專案名稱 + 一句話說明(例如「對繁體中文維基百科連結網絡的互動式分析:社群偵測、語意搜尋、瀏覽量異常偵測」)+ 進入圖探索器的主要 CTA
2. **展示了什麼能力**:3-4 個對應實際功能的簡短說明(Infomap 社群偵測的網絡拓樸分析、Workers AI + pgvector 的語意搜尋、瀏覽量時間序列的統計異常偵測)——讓不熟悉圖論的訪客也能看懂「這是在展示什麼」
3. **架構一覽**:簡短圖示或條列——Python 批次 pipeline → Neon/pgvector → Cloudflare Worker(Hono)→ React/Sigma.js 前端,凸顯跨全端(資料工程+後端+前端+架構)的廣度
4. **拓樸圖截圖或短 GIF**——這是整個專案視覺上最吸引人的東西,不該讓訪客點進去才看得到
5. GitHub repo 連結,以及使用者自行決定是否要放個人聯絡資訊

## 資料管線階段一覽表(移植難度評估)

| # | 階段 | 來源 | 移植難度 |
|---|---|---|---|
| 1 | 連結圖爬取(MediaWiki `generator=links`、redirect 解析、BFS/DFS） | `build_data.py`: `get_article_links`/`add_article`/`process_article`/`build_network` | 邏輯大致可直接搬,但要修 `time` 模組 monkey-patch bug、換成有併發上限的 async、快取檔整合成單一 checkpoint store |
| 2 | 條目簡介擷取 | `build_data.py`: `get_articles_extracts` | 可直接搬 |
| 3 | 瀏覽量歷史 | `build_data.py`: `get_pageviewHistory`/`save_batch_pageviews` | 可直接搬,但需參數化 granularity 以同時產出日/半月兩種資料(舊版只抓 monthly) |
| 4 | Redirect 收斂/「重要條目」過濾 | `build_data.py`: `build_imp_network_with_redirect` | 需要重新評估是否需要——小規模種子下可能是不必要的複雜度,先捨棄,真的爬出過大的圖再考慮加回 |
| 5 | 有向圖建構 | `analyze.py`: `WikiNetwork.create_network`/`_load_network` | 大致可搬,`iterrows()` 迴圈建議換成 `itertuples()`加速 |
| 6 | 邊權重(拓樸相似度) | `analyze.py`: `config_weight_topology`/`graph_utils.get_similarity_topology` | 可直接搬,注意它是非對稱的(`|common|/|neighbors2|`),移植時保留原行為,不要不小心「修正」成對稱版本 |
| 7 | 兩層社群偵測 | `analyze.py`: `config_infomap` | 可直接搬 |
| 8 | 多層社群偵測 | `analyze.py`: `config_infomap_multi_level`/`config_G_list_multi_level_subgraphs` | **捨棄,不移植**(已確認壞掉,且無可用的參考 UI) |
| 9 | 有效子圖擷取 | `analyze.py`: `config_G_list_two_level_effective_subgraphs` | 可搬,但 `min_node_num`/`max_node_num` 需參數化 |
| 10 | 特殊節點標記(hub/authority/betweenness/bridge) | `analyze.py`: `config_two_level_special_nodes` | 可直接搬 |
| 11 | 社群關係 meta-graph | `analyze.py`: `config_G_two_level_community_relation` | 邏輯正確但寫法繞,值得順手重構(同樣輸出,更清楚的程式碼) |
| 12 | GraphML/JSON I/O | `analyze.py`: `graph_utils.*` | 可直接搬,即使最終資料進 Postgres,仍可作為除錯用的中繼產物 |
| 13 | Wikidata 標籤 | `get_tag.py` | **不在 v1 範圍**,列為未來可加的功能(例如搜尋分類篩選) |
| 14 | Embedding 生成 | 無(舊版從未真正呼叫) | **全新撰寫**,見 Phase 3 |
| 15 | 匯出/寫入 Neon | 無 | **全新撰寫**,見 Phase 4 |
| 16 | `convert_graphml_to_json.py` | — | **捨棄**,已確認是空函式,無邏輯可參考 |

## 驗證方式

- **Phase 1-3(pipeline,小型種子)**:`pytest`,MediaWiki API 呼叫用 `vcrpy`/`responses` 錄製成 fixture,確保測試不依賴即時 Wikipedia 狀態。斷言節點/邊數量符合預期、無指向資料集外的 `Directed_Index`、redirect 解析正確收斂。另外保留一支手動執行的「真實」小規模爬取腳本,不放進 CI,作為定期健康檢查。
- **Phase 2(社群)**:每個節點都有 `community`、每個有效子圖都有四個特殊節點標記、社群關係 meta-graph 結構符合預期。
- **Phase 3(embedding)**:每筆擷取文字產出正確維度的向量,且已知相似的一對條目 cosine 相似度高於已知不相似的一對(驗證 embedding 呼叫本身,不只是資料流)。
- **Phase 4(寫入 Neon)**:pipeline 輸出筆數與 DB 筆數一致、對已知節點做 SQL 抽查、對已知條目跑 pgvector `<=>` 查詢確認能查回自己排第一。
- **Phase 5(後端)**:`vitest` 對 `anomaly_detection`/`linear_regression` 純函式做單元測試(直接把 `analysis.py` 的範例輸入輸出當測資,確保行為與 Python 原版一致)。用 `wrangler dev`/Miniflare 接 Neon `dev` branch 做整合測試。
- **Phase 6(前端)**:先用 `shared-types` mock 資料手動檢查(不用等 Phase 5),整合後跑 Playwright 煙霧測試(圖渲染、點擊節點開啟詳情、社群子圖、搜尋、異常表分頁),加一組手機視窗的測試對應響應式版面決定。
- **Phase 8(全規模執行)**:重跑 Phase 1-4 的斷言,額外做「中途強制中斷、確認 checkpoint 能續傳不重爬」的測試。
- **Phase 9(部署)**:正式環境跑一次完整功能的煙霧測試(health check、圖載入、搜尋)才算部署完成。
- **Phase 10(排程)**:手動觸發一次 Cron Trigger 與 GitHub Actions workflow,確認資料正確 upsert 且不會產生重複資料。

## 待使用者決定的事項(可在實作過程中再定案)

- 真實爬取的種子主題/領域(目前用小型 fixture 種子開發,不卡在此決策上)
- Workers AI 具體要用哪個 embedding 模型(需在 Phase 3 開始前選定,會決定資料庫向量欄位維度)
- 是否需要 Wikidata 標籤功能(目前列為 v1 範圍外的待辦)
- 首頁是否要放個人聯絡資訊/身份揭露

## 關鍵參考檔案

- `c:/Users/User/wikiProject/wiki/data_factory/analyze.py`
- `c:/Users/User/wikiProject/wiki/data_factory/build_data.py`
- `c:/Users/User/wikiProject/web_wiki/drizzle/schema.ts`
- `c:/Users/User/wikiProject/web_wiki/src/lib/server/python_api/vector.py`
- `c:/Users/User/wikiProject/web_wiki/src/lib/server/python_api/analysis.py`
- `c:/Users/User/wikiProject/web_wiki/src/routes/two_level_community_relation/+page.svelte`
