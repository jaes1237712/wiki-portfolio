/**
 * Embedding 模型與向量維度的單一真實來源。
 *
 * 離線 pipeline(產生 passage embedding)與線上 Worker(產生 query embedding)
 * 必須用「同一個」Workers AI 模型,否則向量空間不相容、搜尋結果會是垃圾。
 * 換模型 = 換維度 = 必須重建 nodes_passage_vector 資料表與全部 embedding。
 */
export const EMBEDDING_MODEL = '@cf/baai/bge-m3' as const;

/** bge-m3 輸出維度。改模型時這裡與 pipeline/wiki_pipeline/config.py 要一起改。 */
export const EMBEDDING_DIMENSIONS = 1024 as const;
