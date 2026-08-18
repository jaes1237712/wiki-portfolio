import { defineConfig } from 'drizzle-kit';

// DATABASE_URL 一律從環境變數讀,絕不寫死在程式碼裡(舊版 web_wiki/main.py 曾把 DB 密碼寫死當 fallback)。
const url = process.env.DATABASE_URL;
if (!url) {
  throw new Error('DATABASE_URL is required (see .env.example). Neon dev branch 連線字串。');
}

export default defineConfig({
  schema: './src/schema.ts',
  out: './migrations',
  dialect: 'postgresql',
  dbCredentials: { url },
  casing: 'snake_case',
});
