import torch
import torch.nn.functional as F
import numpy as np
import psycopg2
from transformers import AutoTokenizer, AutoModel
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm
import logging
import threading
from fastapi import HTTPException
from pydantic import BaseModel
from enum import Enum
import math
from typing import List, Optional


#DATABASE_URL: postgres://<user>:<redacted>@localhost:5432/wiki_network
# ---------- 1. 參數設定 ----------
EMBED_DIM = 1024  # E5-large-instruct 預設維度
logger = logging.getLogger(__name__)
_model_lock = threading.Lock()
model, tokenizer, device = None, None, None

class EmbedType(str, Enum):
    query = "query"
    passage = "passage"

class SearchCol(str, Enum):
    queryEmbedding = "query_embedding"
    passageEmbedding = "passage_embedding"

MAX_TEXT_LEN = 512

def load_model():
    global model, tokenizer, device
    if model is not None:
        return True
    with _model_lock:
        if model is not None:
            return True
        try:
            import torch
            from transformers import AutoTokenizer, AutoModel
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"Using device: {device}")
            tokenizer = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-large-instruct")
            model = AutoModel.from_pretrained("intfloat/multilingual-e5-large-instruct")
            model.to(device)
            model.eval()
            logger.info("Model loaded successfully.")
        except Exception as e:
            logger.exception("Model loading failed.")
            raise HTTPException(status_code=503, detail="Model loading failed: " + str(e))
    return True

def average_pool(embeddings):
    """
    embeddings: np.ndarray, shape (num_chunks, 1024)
    return: np.ndarray, shape (1024,)
    """
    return np.mean(embeddings, axis=0)

def chunk_text(text, chunk_size=512):
    # 以字元為單位切 chunk，盡量不截斷詞語（可改進為 token 切分）
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def get_text_embeddings(text):
    if tokenizer is None or model is None or device is None:
        load_model()
    chunks = chunk_text(text, 512)
    all_embeddings = []
    for chunk in chunks:
        inputs = tokenizer(chunk, return_tensors="pt", padding=True, truncation=True, max_length=512)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model(**inputs)
            pooled = outputs.last_hidden_state.masked_fill(~inputs['attention_mask'][..., None].bool(), 0.0)
            pooled = pooled.sum(dim=1) / inputs['attention_mask'].sum(dim=1)[..., None]
            pooled = F.normalize(pooled, p=2, dim=1)
            all_embeddings.append(pooled.cpu().numpy()[0])
    all_embeddings = np.stack(all_embeddings)
    if all_embeddings.shape[0] == 1:
        return all_embeddings[0]
    return average_pool(all_embeddings)

def search_similar_entries(text, top_k=50, db_pool=None, idxs: Optional[List[int]] = None):
    conn = db_pool.getconn()
    cur = conn.cursor()
    try:
        text = 'query:' + text
        searchCol = 'passage_embedding'
        queryEmb = get_text_embeddings(text)
        if db_pool is None:
            raise HTTPException(status_code=500, detail="Database connection pool is required.")
        emb_list = queryEmb.tolist()
        if idxs is not None and len(idxs) > 0:
            sql = """
            
            SELECT
                npv.idx,
                npv.similarity,
                n.title,
                n.average_pageviews
            FROM
                (
                    SELECT idx, 1 - (passage_embedding <=> %s::vector) AS similarity
                    FROM nodes_passage_vector
                    WHERE idx = ANY(%s)
                    ORDER BY similarity DESC
                    LIMIT 50
                ) AS npv
            JOIN
                nodes n
            ON
                npv.idx = n.idx
            """
            sql_params = [emb_list, idxs]
        else:
            sql = """
            
            SELECT
                npv.idx,
                npv.similarity,
                n.title,
                n.average_pageviews
            FROM
                (
                    SELECT idx, 1 - (passage_embedding <=> %s::vector) AS similarity
                    FROM nodes_passage_vector
                    ORDER BY similarity DESC
                    LIMIT 50
                ) AS npv
            JOIN
                nodes n
            ON
                npv.idx = n.idx
            """
            sql_params = [emb_list]
        results = []
        cur.execute(sql, tuple(sql_params))
        rows = cur.fetchall()
        for row in rows:
            idx, similarity, title, average_pageviews = row
            results.append({
                'idx': idx,
                'title': title,
                'similarity': float(similarity),
                'average_pageviews': average_pageviews
            })
        if len(results) == 0:
            logger.warning("No results found")
            raise HTTPException(status_code=404, detail="No results found")
        return results
    except psycopg2.Error as e:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.exception("Unknown error")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        db_pool.putconn(conn)
