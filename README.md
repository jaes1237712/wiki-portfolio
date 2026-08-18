# wiki-portfolio

對繁體中文維基百科連結網絡的互動式分析:**社群偵測**、**語意搜尋**、**瀏覽量異常偵測**。

```
Python 批次 pipeline  →  Neon (Postgres + pgvector)  →  Cloudflare Worker (Hono)  →  React + Sigma.js
   爬取 / 建圖 / Infomap          關聯 + 向量查詢              API + Workers AI              互動式拓樸圖
```

## 狀態

https://github.com/jaes1237712/wiki-portfolio


開發中(Phase 0 完成:monorepo 骨架、共用型別、資料庫 schema)。
進度與開發指南見 [CLAUDE.md](CLAUDE.md),完整計畫見 [docs/roadmap.md](docs/roadmap.md)。

## 快速開始

```bash
npm install
npm run build      # 建 packages/shared-types 與 packages/db-schema
npm run typecheck
```

Python pipeline:

```bash
cd pipeline
python -m venv .venv && source .venv/Scripts/activate
pip install -e ".[dev]"
pipeline show-config
```

## 結構

- `packages/shared-types` — 前後端共用的資料型別
- `packages/db-schema` — Drizzle schema(Neon / pgvector)
- `pipeline` — Python 離線批次 pipeline
- `apps/api` — Cloudflare Worker(尚未建立)
- `apps/web` — React SPA(尚未建立)
