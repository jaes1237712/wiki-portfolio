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
│   └── decisions.md    # 決策紀錄 + 待決事項
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
| 1 | Pipeline:爬蟲 + 原始連結圖 | ⬜ 未開始 |
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

**下一步:** 開 Neon 專案 + `dev` branch,跑 `npm run db:push` 把 schema 推上去;然後開始 Phase 1。

## 開發慣例

- **密鑰**:一律走環境變數 / Wrangler secrets。舊版 `web_wiki/main.py` 有寫死的 DB 密碼,絕不重蹈覆轍。
- **CORS**:Worker 只允許自己的 Pages 網域,不要 `*`。
- **型別**:前後端共用的資料形狀一律定義在 `@wiki/shared-types`,不要各自複製一份。
- **Embedding 模型**:`packages/db-schema/src/config.ts` 與 `pipeline/wiki_pipeline/config.py`
  兩處的模型/維度**必須一致**。改模型 = 重建 `nodes_passage_vector` + 重跑全部 embedding。
- **註解語言**:繁體中文(與使用者一致),程式碼識別字用英文。
- **測試**:pipeline 用 pytest(HTTP 用 respx 錄 fixture,不打真的 API);Worker 用 vitest;前端用 Playwright 煙霧測試。
- **不要移植的東西**:多層社群子圖(舊版壞的)、GSAP 可拖曳版面、Cytoscape 渲染邏輯、
  `convert_graphml_to_json.py`(空函式)、Wikidata 標籤(v1 範圍外)。

## 舊專案參考位置

重寫的參考實作在**這個 repo 之外**(使用者本機 `c:/Users/User/wikiProject/`):

- `wiki/data_factory/build_data.py` — 爬蟲(Phase 1 參考)
- `wiki/data_factory/analyze.py` — 建圖、權重、社群偵測(Phase 2 參考)
- `web_wiki/drizzle/schema.ts` — 舊 schema(已改編進 `packages/db-schema`)
- `web_wiki/src/lib/server/python_api/analysis.py` — 異常偵測 / 線性回歸(Phase 5 要移植成 TS)
- `web_wiki/src/lib/server/python_api/vector.py` — 向量搜尋 SQL(Phase 5 參考)
- `web_wiki/src/routes/two_level_community_relation/+page.svelte` — 社群關係 UI(Phase 6 參考)

⚠️ 換裝置時這些檔案不會跟著 repo 走。若要在其他裝置繼續參考,需要另外處理(見 decisions.md 的待決事項)。
