import requests
import json
import time
from typing import List, Optional
import traceback

def get_instance_of(title: str) -> List[dict]:
    """
    直接使用維基百科標題獲取Wikidata instance of (P31)屬性
    
    Args:
        title (str): 維基百科條目標題
        
    Returns:
        List[dict]: 包含instance of信息的字典列表，每個字典包含:
            - id: Wikidata ID
            - label_zh: 中文標籤
            - label_en: 英文標籤
    """
    try:
        # 構建SPARQL查詢，直接使用標題
        url = "https://query.wikidata.org/sparql"
        query = """
        SELECT ?instance ?instanceLabel_zh ?instanceLabel_en WHERE {
          ?item schema:about ?article ;
                schema:isPartOf <https://zh.wikipedia.org/> ;
                schema:name "%s"@zh.
          ?item wdt:P31 ?instance.
          SERVICE wikibase:label { 
            bd:serviceParam wikibase:language "zh,en".
            ?instance rdfs:label ?instanceLabel_zh. FILTER(LANG(?instanceLabel_zh) = "zh")
            ?instance rdfs:label ?instanceLabel_en. FILTER(LANG(?instanceLabel_en) = "en")
          }
        }
        """ % title
        
        headers = {
            'User-Agent': 'Mozilla/5.0 Wiki Research Tool',
            'Accept': 'application/json'
        }
        params = {
            'query': query,
            'format': 'json'
        }
        
        # 發送請求並解析響應
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for item in data['results']['bindings']:
            instance_id = item['instance']['value'].split('/')[-1]
            label_zh = item['instanceLabel_zh']['value']
            label_en = item['instanceLabel_en']['value']
            
            results.append({
                'id': instance_id,
                'label_zh': label_zh,
                'label_en': label_en
            })
            
        return results
        
    except Exception as e:
        print(f"獲取instance of屬性時出錯 (標題: {title}): {str(e)}")
        traceback.print_exc()
        return []

def process_articles_batch(articles: List[dict], output_file: str, batch_size: int = 10):
    """
    批量處理文章並獲取它們的instance of標籤
    
    Args:
        articles (List[dict]): 文章信息列表
        output_file (str): 輸出文件路徑
        batch_size (int): 每批處理的文章數量
    """
    try:
        results = []
        total_articles = len(articles)
        
        for i in range(0, total_articles, batch_size):
            batch = articles[i:i + batch_size]
            print(f"\n處理進度: {i+1}/{total_articles} ({((i+1)/total_articles*100):.1f}%)")
            
            for article in batch:
                title = article['Title']
                print(f"\n處理文章: {title}")
                
                instances = get_instance_of(title)
                if instances:
                    result = {
                        'Index': article['Index'],
                        'Title': title,
                        'instances': instances
                    }
                    results.append(result)
                    print(f"找到 {len(instances)} 個instance of標籤")
                    for inst in instances:
                        print(f"- {inst['label_zh']} ({inst['label_en']})")
                else:
                    print(f"未找到instance of標籤")
                
                # 添加延遲以避免請求過快
                time.sleep(1)
            
            # 每批次完成後保存一次結果
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
                
            print(f"\n已保存當前結果到 {output_file}")
            
    except Exception as e:
        print(f"批量處理文章時出錯: {str(e)}")
        traceback.print_exc()

# 使用示例
if __name__ == "__main__":
    # 從JSON文件讀取文章數據
    input_file = "articles.json"
    output_file = "article_instances.json"
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            articles = json.load(f)
            
        # 批量處理文章
        process_articles_batch(articles, output_file, batch_size=10)
        
    except Exception as e:
        print(f"程序執行出錯: {str(e)}")
        traceback.print_exc()