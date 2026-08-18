# CLAUDE.md — wiki-portfolio 開發指南

> 這份檔案是**跨裝置的單一真實來源**。換一台電腦、隔一段時間回來、或開一個新的 Claude Code
> session,都先讀這份。進度、決策、待辦都記在這裡,不要只留在對話裡。
>
> **每完成一個 Phase 或做出新決策,就更新本檔的「目前進度」與「決策紀錄」。**

## 專案是什麼

對繁體中文維基百科連結網絡的互動式分析作品集網站:爬取條目連結圖 → Infomap 社群偵測 →
語意搜尋(pgvector)→ 瀏覽量異常偵測,前端用 Sigma.js 呈現整張拓樸圖。

目的是展示全端能力(資料工程 + 後端 + 前端 + 架構),所以每一層都要做得像正式產品:
沒有寫死的密鑰、CORS 限制來源、有測試、有排程重算。

完整分階段計畫見 [docs/roadmap.md](docs/roadmap.md)。

## 技術棧(已定案,不要重新討論)

| 層面 | 選擇 |
|---|---|
| 資料管線 | Python 3.11+,離線批次(igraph + Infomap) |
| 資料庫 | Neon(Postgres + pgvector),Drizzle 管 schema |
| 後端 | Cloudflare Workers + Hono |
| Embedding | Cloudflare Workers AI(離線與線上共用同一模型) |
| 前端 | Vite + React SPA → Cloudflare Pages |
| 圖視覺化 | Sigma.js + graphology(react-sigma) |
| 圖表 | Recharts |
| Monorepo | **npm workspaces(不要用 pnpm/yarn)** |
| 排程 | 輕量每日:Cloudflare Cron Trigger;重量週期:GitHub Actions |

選型理由寫在 [docs/decisions.md](docs/decisions.md)。

## Repo 結構

```
wiki-portfolio/
├── apps/
│   ├── web/            # Vite + React SPA(Phase 6,尚未建立)
│   └── api/            # Cloudflare Worker + Hono(Phase 5,尚未建立)
├── packages/
│   ├── shared-types/   # ✅ 前後端共用型別
│   └── db-schema/      # ✅ Drizzle schema + embedding 模型設定
├── pipeline/           # 🚧 Python 離線 pipeline(骨架完成,階段實作見 Phase 1-4)
│   ├── wiki_pipeline/
│   └── tests/
├── docs/
│   ├── roadmap.md      # 完整分階段計畫
│   ├── decisions.md    # 決策紀錄 + 待決事項
│   └── legacy/         # 舊專案參考程式碼(唯讀)
└── .github/workflows/  # 重量重算排程(Phase 10)
```

## 新裝置設定步驟

```bash
git clone <repo> && cd wiki-portfolio

# 1. Node 端(需要 Node 20+)
npm install
npm run build          # 建 packages/*
npm run typecheck

# 2. Python 端(需要 Python 3.11+)
cd pipeline
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash;macOS/Linux 用 .venv/bin/activate
pip install -e ".[dev]"
pipeline show-config            # 確認設定讀得到

# 3. 環境變數(絕不進版控)
cp packages/db-schema/.env.example packages/db-schema/.env   # 填 Neon dev branch 連線字串
```

需要的雲端帳號:Neon(專案 + `dev`/`main` 兩個 branch)、Cloudflare(Workers / Pages / Workers AI)。

## 目前進度

| Phase | 內容 | 狀態 |
|---|---|---|
| 0 | Repo 骨架、npm workspaces、shared-types、db-schema | ✅ 完成(Neon 專案尚未開) |
| 1 | Pipeline:爬蟲 + 原始連結圖(BFS + SQLite checkpoint + 20 個測試) | 🟡 核心完成 |
| 2 | Pipeline:建圖 + 邊權重 + 兩層社群偵測 | ⬜ 未開始 |
| 3 | Pipeline:Workers AI embedding | ⬜ 未開始 |
| 4 | Pipeline:寫入 Neon(**里程碑**,解鎖 5/6 平行開發) | ⬜ 未開始 |
| 5 | 後端 Worker(Hono) | ⬜ 未開始 |
| 6 | 前端 React app | ⬜ 未開始 |
| 7 | 小型資料集整合測試 | ⬜ 未開始 |
| 8 | 全規模 pipeline 執行(真實主題) | ⬜ 未開始 |
| 9 | 部署 | ⬜ 未開始 |
| 10 | 排程重算 | ⬜ 未開始 |
| 11 | 作品集包裝(首頁) | ⬜ 未開始 |

**Phase 1 已完成的部分:** `wiki_pipeline/state.py`(SQLite checkpoint,取代舊版 5 個 JSON 快取檔)、
`wiki_api.py`(async + 併發上限 + 退避重試 + 簡繁/redirect 標題收斂)、`scrape.py`(逐層 BFS、
每批一個交易、可續傳、原子寫出 `wiki_network.json`)、`tests/`(respx 假 API,不打真的 Wikipedia)。
`zh.py`(OpenCC s2twp 顯示標題)。已對真實 API 實測:`圖論` depth 1 → 251 節點,
標題正確收斂(`圖論`→正式標題 `图论`)且顯示標題轉成台灣繁體(`计算机科学`→`電腦科學`),
續跑 0 次額外請求。

**Phase 1 還沒做:** 條目簡介批次落庫(`fetch_extracts` 已寫好但還沒接成 stage)、瀏覽量抓取
(日 + 半月兩種 granularity)。

**Git 狀態:** 本機 repo(main branch)已有 3 個 commit,**還沒推到 GitHub**。
已決定要開公開 repo;gh CLI 已安裝,缺 `gh auth login` 後執行
`gh repo create wiki-portfolio --public --source=. --push`。

**下一步:** 推上 GitHub → 開 Neon 專案 + `dev` branch → `npm run db:push`;
或直接接 Phase 2(建圖 + 邊權重 + 兩層社群偵測)。

## 開發慣例

- **密鑰**:一律走環境變數 / Wrangler secrets。舊版 `web_wiki/main.py` 有寫死的 DB 密碼,絕不重蹈覆轍。
- **CORS**:Worker 只允許自己的 Pages 網域,不要 `*`。
- **型別**:前後端共用的資料形狀一律定義在 `@wiki/shared-types`,不要各自複製一份。
- **Embedding 模型**:`packages/db-schema/src/config.ts` 與 `pipeline/wiki_pipeline/config.py`
  兩處的模型/維度**必須一致**。改模型 = 重建 `nodes_passage_vector` + 重跑全部 embedding。
- **註解語言**:繁體中文(與使用者一致),程式碼識別字用英文。
- **繁簡**:zh 維基的正式標題簡繁混雜(「圖論」的實際頁面是「图论」)。API 一律帶
  `converttitles=1` + `variant=zh-tw`,並在展開前用 `resolve_titles` 把標題收斂,否則同一條目
  會變成兩個節點。正式標題(`nodes.title`)是圖的 ID 也是維基連結用的標題;顯示一律用
  `nodes.title_display`(pipeline 端 OpenCC `s2twp` 轉出的台灣繁體)。
- **測試**:pipeline 用 pytest(HTTP 用 respx 錄 fixture,不打真的 API);Worker 用 vitest;前端用 Playwright 煙霧測試。
- **不要移植的東西**:多層社群子圖(舊版壞的)、GSAP 可拖曳版面、Cytoscape 渲染邏輯、
  `convert_graphml_to_json.py`(空函式)、Wikidata 標籤(v1 範圍外)。

## 舊專案參考程式碼

重寫的參考實作已複製進 [docs/legacy/](docs/legacy/)(唯讀,不要 import、不要改、不要跑),
換裝置時跟著 repo 走。原始檔在使用者本機 `c:/Users/User/wikiProject/{wiki,web_wiki}/`。
檔案對照與已知的坑見 [docs/legacy/README.md](docs/legacy/README.md)。
