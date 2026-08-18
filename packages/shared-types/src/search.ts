/** pgvector 語意搜尋的型別。 */

export interface SearchResult {
  idx: number;
  title: string;
  introduction: string | null;
  community: number;
  /** 1 - cosine distance,越大越相似。 */
  similarity: number;
}

export interface SearchQuery {
  q: string;
  /** 回傳筆數上限,預設 10。舊版把這個參數忽略掉、SQL 寫死 LIMIT 50,新版必須真的用它。 */
  topK?: number;
}
