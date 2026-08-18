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
`DEV_SEEDS = ["圖論", "網絡科學", "複雜網絡"]`(三個都實測存在;原本寫的「社群發現」zh 維基沒有這個條目)、depth 2。這不是最終作品集主題,只是讓
Phase 1-6 有東西可開發,不被主題決策卡住。社群過濾門檻在 dev 設定裡調成 min=3/max=200
(舊版寫死 50/500,小圖會濾光所有社群)。

### 10. 標題以維基的「正式標題」為圖的 ID
zh 維基的正式頁面標題簡繁混雜(「圖論」的實際頁面是「图论」、「網絡科學」是「网络科学」)。
所有 API 呼叫都帶 `converttitles=1` + `variant=zh-tw`,並在展開前用 `WikiClient.resolve_titles`
把佇列裡的標題收斂成正式標題,否則同一個條目會變成兩個節點、圖也會斷開。
`displaytitle` 實測**不會**做繁簡轉換,所以「顯示用繁體標題」要另外想辦法(見待決事項 G)。

### 11. Phase 1 爬蟲改成逐層 BFS
舊版是遞迴 DFS + 序列化請求。新版一層一層跑,每批(預設 concurrency×4)先批次收斂標題、
再併發抓連結、最後整批寫進一個 SQLite 交易。好處:進度可續傳、中斷不會留半筆、
同一批裡指向同一頁的別名只抓一次。

### 12. 顯示標題用 OpenCC(s2twp)在 pipeline 端轉換
`nodes.title` 存維基正式標題(圖的 ID、組維基連結用),`nodes.title_display` 存 OpenCC
`s2twp` 轉出的台灣繁體,前端顯示一律用後者。實測:「计算机科学」→「電腦科學」、
「人工智能」→「人工智慧」、「数据结构」→「資料結構」,與 MediaWiki `variant=zh-tw`
回傳的簡介內文用詞一致(都用「網路/演算法/軟體」),標題與內文才不會打架。

選 pipeline 端而不是前端轉換:前端要多載一份字典、上千個節點每次渲染都要轉;
pipeline 只在爬取時轉一次,而且搜尋時兩種寫法都能比對。

### 13. Phase 2 用 igraph 內建的 `community_infomap`,不裝 infomap 套件
舊版 `analyze.py` import 了 `infomap`,但實際跑的是 `G.community_infomap()`(igraph 內建)。
新版照做,少一個原生依賴,GitHub Actions 的重算 workflow 也少一個編譯風險。

### 14. meta-graph 不建「沒有連結」的社群配對邊
舊版對所有社群兩兩建邊,沒有跨社群連結的邊 `connections_num=0`、`distance=inf`。
這種邊會讓加權 pagerank(權重 0)與加權 betweenness(權重 inf)失去意義,
而且對前端只是雜訊。新版只建 `connections_num > 0` 的邊;center 之間在有向圖上走不到時,
distance 給「最遠有限距離 + 1」而不是 inf。資訊等價,數值可用。

### 15. 主畫面的「拓樸圖」= 社群關係 meta-graph
沿用舊版的資訊架構:主畫面不是整張連結圖(太大),而是每個有效社群 4 個特殊節點
(hub / authority / center / bridge)構成的關係圖,點進社群才看該社群的子圖。
⚠️ 這件事與 `packages/db-schema` 目前的 `topology_nodes` 註解(寫成「全圖節點」)不一致,
Phase 4 要一起處理,見待決事項 H。

### 16. 社群偵測固定亂數種子
Infomap 是隨機演算法:同一張圖連跑兩次,實測給出 35 / 36 / 39 個社群,membership 也不同。
社群編號會寫進資料庫、也會出現在前端網址裡,每週重算就換一次號碼是不能接受的。
`detect_communities()` 預設用 `DEFAULT_SEED = 20260818`(實測固定種子兩次跑出完全相同的
membership);要評估分群穩不穩定時傳 `seed=None`。

### 17. meta-graph 一個條目只有一個頂點
同一個條目常常同時是 hub 與 center(社群裡最大的節點通吃),舊版是每個角色各建一個頂點,
前端就會畫出重複節點。新版一個 idx 只建一個頂點,角色合併成 `roles`(逗號分隔)。

### 18. 瀏覽量只抓每日,半月/平均/社群加總都在本地算
舊版只抓 monthly,拿不到日資料就做不了每日異常偵測。新版一律抓 daily,半月(每月 1-15 標成
01、16-月底標成 16)、平均、社群加總都用 `pageviews.py` 在本地算:少打一輪 API,而且兩種
粒度的數字保證對得起來。

⚠️ 資料量:13,085 個條目 × 365 天 ≈ 478 萬筆。本機 SQLite 沒問題,但 Neon 免費方案只有
0.5 GB,估計光這張表加索引就要 300 MB 以上。Phase 4 要決定怎麼處理(見待決事項 I)。

### 19. 抓簡介的批次大小是 20,不是 50
MediaWiki TextExtracts 每個請求最多回 20 筆 extract,超過的部分靜默省略(不報錯、沒有
warnings)。實測用 50 個標題一批,13,085 個條目只有 5,240 個拿到簡介 —— 剛好 40% = 20/50。
`fetch_extracts` 現在超過 20 個標題會直接丟 ValueError,寧可當場爆掉也不要靜默漏資料。

### 20. 瀏覽量抓取併發上限 6,且開發階段不抓滿
實測 Wikimedia REST pageviews API:併發 6 抓 100 個條目 0 失敗;併發 12 持續抓大量條目時
會被限流,約 10% 的條目重試 4 次後仍失敗(續跑會自動重抓)。`PageviewsConfig.concurrency`
預設 6,並在 429/503 時尊重 `Retry-After` 標頭。

瀏覽量不是這個作品集的核心賣點(核心是連結網絡 + 社群偵測 + 語意搜尋),所以開發階段
只抓到約 5,700 個條目(160 萬筆日資料)就停,不花 45 分鐘抓滿 —— 這些真實資料足夠開發
Phase 4-6,而且比寫一份之後要丟掉的 mock 產生器省事。全量抓取留到 Phase 8。

### 21. 探索性實驗的數字要進版控(腳本,不只是結論)
2026-08-19 的討論靠幾個一次性腳本量出了會改變架構的數字(封閉度 2.4%、跨群邊 7%、
瀏覽量集中度、conductance 排序)。這些腳本收進 `pipeline/experiments/`,理由是
**一個沒辦法被重跑的數字,不能拿來做架構決策**。

它們刻意不進 CI、不寫測試、不寫入任何東西 —— 是探索工具,不是 pipeline 的一部分。
維基百科本身會變,所以重跑的數字不會與文件完全一致;但結論(排序、量級、方向)
應該還成立,如果連結論都翻了就是真的發現,要回去改文件。

### 22. 資料策略的討論記錄與決策紀錄分開放
[data-strategy.md](data-strategy.md) 放**還在收斂中**的設計,每一節標
[實測]/[提議]/[待驗]/[待決];decisions.md 只放**已定案**的。

理由:2026-08-19 那次討論產出了大量有數字支撐但還沒定案的提議(三層架構、
conductance 邊界、每日瀏覽量不進 Neon)。全部寫進 decisions.md 會讓「已定案」
這件事失去意義,新 session 會把提議當成規格照做;全部只留在對話裡則會遺失。

**規則:提議定案時才搬進 decisions.md,並註明「取代 #N」。**

## ⚠️ 被 2026-08-19 討論修訂、但尚未定案的決策

以下決策**仍然有效**(還沒被取代),但 [data-strategy.md](data-strategy.md) 提出了
有數字支撐的修訂方向。定案前不要照舊決策實作 Phase 3-8,也不要當它們已經改了。

| 決策 | 修訂方向 | 依據 |
|---|---|---|
| **#6** 排程拆成每日 Cron + 每週 Actions | 每日 Cron 沒工作了(日瀏覽量不進 Neon 之後) | data-strategy.md 5.1 |
| **#15** 主畫面拓樸圖 = 社群關係 meta-graph | 改成三層:L1 主題地圖 / L2 子社群地圖 / L3 主題內部圖 | data-strategy.md 2 |
| **#16** 社群偵測固定亂數種子 | 只解決「同次重跑」,沒解決「跨週編號對應」 | data-strategy.md 5.5 |
| **#18** 瀏覽量只抓每日 | 抓法不變,但**不進 Neon**(改用 Wikimedia API 按需抓,已驗證 CORS `*`),而且只抓抽樣的 10% | data-strategy.md 4.3、5.4 |
| **Phase 1/8 爬取策略** | 從「扁平 BFS + 深度」改成「共享池 + 節點預算保險絲 + conductance 邊界」 | data-strategy.md 1、3 |

## 待決事項

| # | 待決 | 何時需要 | 現況 |
|---|---|---|---|
| A | 真實爬取的種子主題/領域 | Phase 8 前 | 先用 DEV_SEEDS 開發 |
| B | Embedding 模型最終確認 | Phase 3 前 | 暫定 bge-m3(1024 維) |
| ~~C~~ | 舊專案參考檔案要不要複製進 repo | — | ✅ 已決:複製進 `docs/legacy/`(vector.py 裡寫死的 DB 密碼已塗掉) |
| ~~D~~ | GitHub repo 公開還是私有 | — | ✅ 已決:公開(Actions 分鐘數免費無上限) |
| E | 首頁是否放個人聯絡資訊 | Phase 11 | 未決 |
| F | 是否要做 Wikidata 標籤功能 | v1 之後 | 目前排除在 v1 外 |
| ~~I~~ | 每日瀏覽量進 Neon 的策略 | — | ✅ **不進**。Wikimedia pageviews API 實測回 `access-control-allow-origin: *` 與 `max-age=14400` —— 它本來就開放瀏覽器直接打並幫我們 CDN 快取。改成 Worker 代打 + Cache API,省 280 MB。異常偵測改在 pipeline 端算,只把超過閾值的 3.9% 寫進 Neon。見 data-strategy.md 4.3 |
| H | `topology_nodes/edges` 到底存 meta-graph 還是全圖 | Phase 4 前 | 被三層架構取代,要改成 L1/L2/L3 三組表 —— 等三層架構定案再一起處理。見 data-strategy.md 9 |
| **J** | **主題怎麼選**(維基百科「基礎條目」當 taxonomy vs 手動列種子) | 實驗 1 之後 | 未決,產品決策。**先想清楚要吸引的讀者是誰** |
| **K** | 主題可以重疊嗎(「特徵值分解」同屬線性代數與機器學習) | 同上 | 未決,傾向允許重疊並把「共享 N 個條目」當成一種邊 |
| **L** | 幾個主題 | 同上 | 未決,傾向 20(超過 50 則 L1 自己需要再分群) |
| **M** | 主題大小的保險絲設多少 | 同上 | 未決,傾向 1,500(超過就人工檢查種子是不是太寬) |
| ~~G~~ | 顯示用的繁體標題怎麼產生 | — | ✅ 已決:pipeline 端 OpenCC `s2twp` → `nodes.title_display`(見決策 12) |
