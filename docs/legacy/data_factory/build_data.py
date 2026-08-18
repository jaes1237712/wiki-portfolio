import requests
import pandas as pd
import time
import json
import os
from tqdm import tqdm
import numpy as np
import csv
import networkx as nx  # 添加 networkx 引入
from datetime import datetime, timedelta
import traceback
import tempfile
import ijson

class WikiNetworkBuilder:
    def __init__(self, user_agent='IlyaForLessonResearch (b10202052@ntu.edu.tw)', load_file='output/wiki_network.json'):
        """
        初始化維基百科條目網絡構建器
        
        參數:
            user_agent (str): 發送API請求時使用的User Agent
            load_file (str): 要讀取的JSON文件路徑
        """
        self.user_agent = user_agent
        self.headers = {'User-Agent': user_agent}
        self.api_url = "https://zh.wikipedia.org/w/api.php"
        
        # 初始化資料結構
        if os.path.exists(load_file):
            # 讀取現有的JSON文件
            with open(load_file, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # 將JSON數據轉換為DataFrame
            self.data = pd.DataFrame(json_data)
            
            # 重建標題到索引的映射
            self.title_to_index = dict(zip(self.data['Title'], self.data['Index']))
            
            # 設置下一個可用的索引
            self.next_index = self.data['Index'].max() + 1
        else:
            # 如果文件不存在，創建新的DataFrame
            self.data = pd.DataFrame(columns=['Index', 'Title', 'Directed_Index'])
            self.title_to_index = {}
            self.next_index = 1
        
        # 排除的名稱空間
        self.excluded_namespaces = ["Category:", "分類:", "Portal:", "門戶:", 
                                    "Wikipedia:", "維基百科:", "File:", "檔案:",
                                    "Help:", "幫助:", "Template:", "模板:",
                                    "User:", "用戶:", "Talk:", "討論:"]
        
        # 已處理的條目集合，從現有數據初始化
        self.processed_titles = set()
        
        # 添加索引映射緩存
        self.index_mapping = {}
        self.index_mapping_file = 'caches/index_mapping_cache.json'
        
        # 載入索引映射緩存
        if os.path.exists(self.index_mapping_file):
            try:
                with open(self.index_mapping_file, 'r', encoding='utf-8') as f:
                    self.index_mapping = json.load(f)
                print(f"已從緩存載入 {len(self.index_mapping)} 個索引映射")
            except:
                print("警告：無法讀取索引映射緩存文件，將使用空字典")
        self.imp_titles = {}
        self.imp_titles_file = 'output/imp_titles.json'
        # 載入索引映射緩存
        if os.path.exists(self.imp_titles_file):
            try:
                with open(self.imp_titles_file, 'r', encoding='utf-8') as f:
                    self.imp_titles = json.load(f)['titles']
                print(f"已從緩存載入 {len(self.imp_titles)} 個重要條目")
            except:
                print("警告：無法讀取重要條目文件，將使用空字典")
        # 篩選重要條目
        self.imp_data_file = 'output/imp_network_with_redirect.json'
        
        self.imp_data = []
        if os.path.exists(self.imp_data_file):
            with open(self.imp_data_file, 'r', encoding='utf-8') as f:
                for item in ijson.items(f, 'item'):
                    # 根據需要保留欄位，例如只保留 Index, Title, Directed_Index
                    self.imp_data.append({
                        'Index': item.get('Index'),
                        'Title': item.get('Title'),
                        'Directed_Index': item.get('Directed_Index'),
                        'Views': item.get('Views')
                    })
            self.imp_data = pd.DataFrame(self.imp_data)
            print(f"已篩選出 {len(self.imp_data)} 個重要條目")

        # 添加重定向緩存
        self.redirect_cache = {}
        self.redirect_cache_file = 'caches/redirect_cache.json'
        
        # 載入重定向緩存
        if os.path.exists(self.redirect_cache_file):
            try:
                with open(self.redirect_cache_file, 'r', encoding='utf-8') as f:
                    self.redirect_cache = json.load(f)
                print(f"已從緩存載入 {len(self.redirect_cache)} 個重定向映射")
            except:
                print("警告：無法讀取重定向緩存文件，將使用空字典")
        # 添加緩存字典
        self.valid_articles_cache = {}
        self.cache_file = 'caches/article_cache.json'
        self.processed_cache_file = 'caches/processed_titles_cache.json'
        
        # 已處理的條目集合，從緩存初始化
        self.processed_titles = set()
        if os.path.exists(self.processed_cache_file):
            try:
                with open(self.processed_cache_file, 'r', encoding='utf-8') as f:
                    self.processed_titles = set(json.load(f))
                print(f"已從緩存載入 {len(self.processed_titles)} 個已處理條目")
            except:
                print("警告：無法讀取已處理條目緩存文件，將使用空集合")
        
        # 如果緩存文件存在，載入它
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.valid_articles_cache = json.load(f)
            except:
                print("警告：無法讀取緩存文件，將使用空緩存")
        # 添加瀏覽量緩存
        self.views_cache = set()
        self.views_cache_file = 'caches/views_cache.json'
        
        # 載入瀏覽量緩存
        if os.path.exists(self.views_cache_file):
            try:
                with open(self.views_cache_file, 'r', encoding='utf-8') as f:
                    self.views_cache = set(json.load(f))
                print(f"已從緩存載入 {len(self.views_cache)} 個已處理瀏覽量數據")
            except:
                print("警告：無法讀取瀏覽量緩存文件，將使用空集合")    
    

    def get_article_links(self, title_origin):
        """
        獲取指定維基百科條目中的所有條目連結，並維護重定向緩存
        
        參數:
            title (str): 維基百科條目的標題
                
        返回:
            list: 與該條目有連結的所有條目標題列表
        """
        params = {
            "action": "query",
            'generator': 'links',
            "titles": title_origin,
            "format": "json",
            "gpllimit": "500",
            "redirects": 1,
            "utf8": 1,
            'gplnamespace': 0
        }
        
        try:
            article_links = []
            continue_params = {}
            redirect_updated = False
            
            while True:
                import time
                time.start = time.time()
                current_params = {**params, **continue_params}
                response = requests.get(self.api_url, params=current_params, headers=self.headers)
                data = response.json()
                if "error" in data:
                    print(f"錯誤：獲取 '{title}' 的連結時出錯: {data['error']['info']}")
                    break
                
                # 處理重定向並更新緩存
                if "query" in data and "redirects" in data["query"]:
                    for redirect in data["query"]["redirects"]:
                        from_title = redirect["from"]
                        to_title = redirect["to"]
                        if from_title not in self.redirect_cache or self.redirect_cache[from_title] != to_title:
                            self.redirect_cache[from_title] = to_title
                            redirect_updated = True
                
                # 獲取頁面連結
                if "query" in data and "pages" in data["query"]:
                    for page_data in data["query"]["pages"].values():
                        if "missing" not in page_data:
                            title = page_data["title"]
                            article_links.append(title)
                
                if "continue" in data:
                    continue_params = data["continue"]
                else:
                    break
                
                time.sleep(0.1)
            
            # 如果有新的重定向關係，保存緩存
            if redirect_updated:
                print(f"重定向緩存已更新，當前共有 {len(self.redirect_cache)} 個映射")
            time.end = time.time()
            time.diff = time.end - time.start
            print(f"請求 '{title_origin}' 連結耗時: {time.diff:.2f}秒")
                
            return article_links
                
        except Exception as e:
            print(f"錯誤：獲取 '{title}' 的連結時發生異常: {str(e)}")
            traceback.print_exc()
            return []
  
    def get_articles_extracts(self, titles, batch_size=50, output_file='output/article_extracts.json'):
        """
        批量獲取維基百科條目的簡介(extracts)並保存
        
        參數:
            titles (list): 維基百科條目標題列表
            batch_size (int): 每批處理的條目數量，最大50（API限制）
            output_file (str): 輸出文件路徑
                
        返回:
            list: 包含條目信息的字典列表
        """
        try:
            # 創建輸出目錄
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # 載入現有數據（如果存在）
            extracts_data = []
            title_set = set()  # 用於追踪已處理的標題
            if os.path.exists(output_file):
                with open(output_file, 'r', encoding='utf-8') as f:
                    extracts_data = json.load(f)
                    title_set = {item['title'] for item in extracts_data}
                    print(f"已載入現有簡介數據：{len(extracts_data)}筆")

            # 過濾掉已經處理過的標題
            titles_to_process = [t for t in titles if t not in title_set]
            if not titles_to_process:
                print("所有條目都已經處理過了")
                return extracts_data
            
            print(f"開始處理{len(titles_to_process)}個條目的簡介...")
            
            # 分批處理
            for i in tqdm(range(0, len(titles_to_process), batch_size), desc="處理批次"):
                batch_titles = titles_to_process[i:i + batch_size]
                continue_params = {}
                
                while True:
                    # 構建API請求
                    params = {
                        "action": "query",
                        "format": "json",
                        "titles": "|".join(batch_titles),
                        "prop": "extracts",
                        "exintro": True,  # 只獲取導言部分
                        "explaintext": True,  # 純文本格式
                        "redirects": True,  # 處理重定向
                        "converttitles": True,  # 轉換標題格式
                        "utf8": 1,
                        **continue_params
                    }
                    
                    try:
                        response = requests.get(self.api_url, params=params, headers=self.headers)
                        data = response.json()
                        
                        # 處理重定向映射
                        redirects = {}
                        if "query" in data and "redirects" in data["query"]:
                            for redirect in data["query"]["redirects"]:
                                redirects[redirect["from"]] = redirect["to"]
                        
                        if "query" in data and "pages" in data["query"]:
                            for page_id, page_data in data["query"]["pages"].items():
                                if "title" in page_data and "extract" in page_data:
                                    title = page_data["title"]
                                    # 檢查是否是重定向後的標題
                                    original_title = title
                                    for from_title, to_title in redirects.items():
                                        if to_title == title:
                                            original_title = from_title
                                            break
                                    
                                    extract = page_data["extract"].strip()
                                    if extract and title in self.title_to_index:  # 確保有簡介且能找到index
                                        article_info = {
                                            "title": title,
                                            "index": self.title_to_index[title],
                                            "extract": extract
                                        }
                                        if original_title != title:
                                            article_info["redirect_from"] = original_title
                                        
                                        extracts_data.append(article_info)
                                        title_set.add(title)
                        
                        # 檢查是否需要繼續
                        if "continue" in data:
                            continue_params = data["continue"]
                        else:
                            break
                            
                    except Exception as e:
                        print(f"處理批次時發生錯誤: {str(e)}")
                        traceback.print_exc()
                        break
                        
                    # 避免請求過快
                    time.sleep(0.1)
                
                # 每完成一個批次就保存一次數據
                if extracts_data:  # 確保有數據才保存
                    self.safe_write_json(extracts_data, output_file)
                    print(f"\n已保存當前批次數據，目前共 {len(extracts_data)} 筆")
            
            # 移除重複的條目，保留第一個出現的條目
            unique_extracts = {}
            for item in extracts_data:
                title = item['title']
                if title not in unique_extracts:
                    unique_extracts[title] = item
            
            # 轉換回列表
            extracts_data = list(unique_extracts.values())
            print(f"\n移除重複條目後剩餘 {len(extracts_data)} 筆")

            # 最後再保存一次以確保所有數據都已保存
            if extracts_data:
                self.safe_write_json(extracts_data, output_file)
            
            print(f"\n處理完成！共獲取了 {len(extracts_data)} 個條目的簡介")
            print(f"數據已保存至: {output_file}")
            
            # 顯示一些統計信息
            if extracts_data:
                print("\n數據統計:")
                print(f"- 總條目數: {len(extracts_data)}")
                print(f"- 平均簡介長度: {sum(len(item['extract']) for item in extracts_data) / len(extracts_data):.1f} 字")
                print(f"- 最短簡介長度: {min(len(item['extract']) for item in extracts_data)} 字")
                print(f"- 最長簡介長度: {max(len(item['extract']) for item in extracts_data)} 字")
                redirects_count = sum(1 for item in extracts_data if 'redirect_from' in item)
                print(f"- 重定向條目數: {redirects_count}")
            
            return extracts_data
            
        except Exception as e:
            print(f"獲取條目簡介時發生錯誤: {str(e)}")
            traceback.print_exc()
            return []   

    def add_article(self, title):
        """
        將文章添加到資料集中，若已存在則返回其索引
        
        參數:
            title (str): 維基百科條目的標題
            
        返回:
            int: 條目的索引值
        """
        # 檢查條目是否已經存在
        if title in self.title_to_index:
            return self.title_to_index[title]
        
        # 新增條目到資料集
        index = self.next_index
        # 準備JSON數據
        set_index_flag = False
        if 'Index' not in self.data.columns:
            self.data = self.data.reset_index('Index')
            set_index_flag = True
    
        self.data.loc[len(self.data)] = {
            'Index': index,
            'Title': title,
            'Directed_Index': []
            # 沒有指定 'views'
        }
        print(f'新增{title}至{index}')      
        self.title_to_index[title] = index
        self.next_index += 1
        if set_index_flag:
            self.data = self.data.set_index('Index')
        return index
    
    def process_article(self, title, depth=1, current_depth=0):
        """
        處理一個條目及其連結，可選擇遞迴處理
        
        參數:
            title (str): 條目標題
            depth (int): 遞迴深度，1表示只處理直接連結，2表示處理連結的連結，依此類推
            current_depth (int): 當前遞迴深度，內部使用
            
        返回:
            bool: 處理是否成功
        """
        # 避免重複處理
        if title in self.processed_titles:
            return True
        
        # 標記為已處理
        self.processed_titles.add(title)
        
        # 將當前條目添加到資料集
        article_index = self.add_article(title)
        
        # 獲取條目連結
        print(f"正在處理條目: {title} (索引: {article_index}, 深度: {current_depth+1}/{depth})")
        links = self.get_article_links(title)
        
        # 處理找到的連結
        directed_indices = []
        for link_title in links:
            link_index = self.add_article(link_title)
            directed_indices.append(link_index)
            
            # 如果還沒到達最大深度，繼續處理連結的條目
            if current_depth + 1 < depth and link_title not in self.processed_titles:
                # 避免過快發送請求
                time.sleep(0.5)
                self.process_article(link_title, depth, current_depth + 1)
        if 'Index' in self.data.columns:
            self.data = self.data.set_index('Index')
            if 'Index' not in self.data.columns:
                self.data.at[article_index, 'Directed_Index'] = directed_indices
            else:
                raise ValueError('data沒有Index，無法設定set_index')
        else:
            self.data.at[article_index, 'Directed_Index'] = directed_indices

        # 在完全處理完當前條目後，才將其標記為已處理
        self.processed_titles.add(title)
        return True
    
    def build_network(self, seed_titles, depth=1):
        """
        從種子條目開始構建網絡
        
        參數:
            seed_titles (list): 種子條目標題列表
            depth (int): 處理深度
            
        返回:
            pd.DataFrame: 構建好的網絡數據
        """
        # 為了快速查詢
        self.data = self.data.set_index('Index')
        count = 0
        total = 0
        clean_titles = []
        for title in seed_titles:
            if title not in self.processed_titles:
                total += 1
                clean_titles.append(title)
        
        for title in clean_titles:
            if title not in self.processed_titles:
                time.state = time.time()
                self.process_article(title, depth)
                # 避免過快發送請求
                count += 1
                time.end = time.time()
                time.diff = time.end - time.state
                print(f"{count}/{total} 耗時: {time.diff:.2f}秒")
                if count % 1000 == 0:
                    self.save_to_files()  # 每處理一千個條目就保存一次
                    self.safe_write_json(self.redirect_cache, self.redirect_cache_file)
                    print(f"已儲存 {count} 個條目，當前索引: {self.next_index}")
        self.save_to_files()  # 最後保存一次
        self.safe_write_json(self.redirect_cache, self.redirect_cache_file)
        return self.data
    
    def analyze_network(self):
        """
        分析構建的網絡結構
        
        返回:
            dict: 包含網絡分析結果的字典
        """
        # 計算基本統計信息
        total_articles = len(self.data)
        total_links = sum(len(links) for links in self.data['Directed_Index'])
        avg_links = total_links / total_articles if total_articles > 0 else 0
        
        # 計算每個條目的入度（被引用次數）
        in_degrees = {}
        for index in self.data['Index']:
            in_degrees[index] = 0
            
        for _, row in self.data.iterrows():
            for linked_index in row['Directed_Index']:
                if linked_index in in_degrees:
                    in_degrees[linked_index] += 1
        
        # 找出最高入度的條目（最多被引用的）
        top_in_degree = sorted(in_degrees.items(), key=lambda x: x[1], reverse=True)[:10]
        top_in_degree_titles = []
        for idx, count in top_in_degree:
            title = self.data[self.data['Index'] == idx]['Title'].values[0]
            top_in_degree_titles.append((title, count))
        
        # 計算出度（引用其他條目數量）
        out_degrees = [(row['Title'], len(row['Directed_Index'])) for _, row in self.data.iterrows()]
        top_out_degree = sorted(out_degrees, key=lambda x: x[1], reverse=True)[:10]
        
        
        # 更新分析結果字典
        analysis = {
            'total_articles': total_articles,
            'total_links': total_links,
            'avg_links_per_article': avg_links,
            'top_referenced_articles': top_in_degree_titles,
            'top_referencing_articles': top_out_degree,
            # 'top_betweenness_centrality': top_betweenness_titles  # 添加 betweenness centrality 結果
        }
        
        return analysis
    
    def get_pageviewHistory(self,title, startDate, endDate,granularity="monthly"):
        """
        獲取繁體中文維基百科特定條目在指定時間段內的瀏覽量歷史數據
        
        參數:
            title (str): 維基百科條目標題
            startDate (str): 開始日期，格式為 'YYYYMMDD'
            endDate (str): 結束日期，格式為 'YYYYMMDD'
            
        返回:
            pandas.DataFrame: 包含日期和瀏覽量的資料框
        """
        # 確保日期格式正確 (YYYYMMDD)
        try:
            start_date = datetime.strptime(startDate, '%Y%m%d')
            end_date = datetime.strptime(endDate, '%Y%m%d')
        except ValueError:
            print("日期格式錯誤，請使用 'YYYYMMDD' 格式")
            return pd.DataFrame(columns=['date', 'pageviews'])
        
        # 維基百科 Pageviews API 端點
        api_url = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
        
        # 請求參數設置
        project = "zh.wikipedia"  # 繁體中文維基百科
        access = "all-access"     # 所有訪問類型
        agent = "user"            # 只計算用戶訪問，不包括機器人
        
        # 構建 API URL
        url = f"{api_url}/{project}/{access}/{agent}/{title}/{granularity}/{startDate}/{endDate}"
        
        # 設置自定義 User-Agent 標頭
        headers = {
            'User-Agent': 'IlyaForLessonResearch (b10202052@ntu.edu.tw)'
        }
        
        try:
            # 發送 GET 請求
            response = requests.get(url, headers=headers)
            
            # 檢查響應狀態
            if response.status_code == 200:
                data = response.json()
                
                # 提取瀏覽量數據
                pageviews_data = []
                for item in data.get('items', []):
                    date_str = item.get('timestamp', '')[:8]  # 格式為 YYYYMMDD
                    # 轉換成更易讀的日期格式 YYYY-MM-DD
                    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                    pageviews = item.get('views', 0)
                    pageviews_data.append({'date': formatted_date, 'pageviews': pageviews})
                
                # 創建 DataFrame
                df = pd.DataFrame(pageviews_data)
                return df
            
            elif response.status_code == 404:
                print(f"找不到條目 '{title}' 或該條目在指定時間段內沒有瀏覽數據")
                return pd.DataFrame(columns=['date', 'pageviews'])
            
            else:
                print(f"API 請求失敗，狀態碼: {response.status_code}, 錯誤信息: {response.text}")
                return pd.DataFrame(columns=['date', 'pageviews'])
        
        except Exception as e:
            print(f"發生錯誤: {str(e)}")
            return pd.DataFrame(columns=['date', 'pageviews'])
    
    def safe_write_json(self, data, target_path):
        """
        安全地將JSON數據寫入文件
        
        參數:
            data: 要寫入的數據
            target_path (str): 目標文件路徑
        """
        dirpath = os.path.dirname(target_path) or "."
        os.makedirs(dirpath, exist_ok=True)
        
        # 建立暫存檔並寫入資料
        with tempfile.NamedTemporaryFile("w", dir=dirpath, delete=False, encoding='utf-8') as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            temp_path = tmp.name
        
        # 用原子方式覆蓋原始檔案
        os.replace(temp_path, target_path)

    def save_to_files(self, prefix="wiki_network"):
        """
        將構建好的網絡保存到文件
        
        參數:
            prefix (str): 文件名前綴
            
        返回:
            str: 保存的JSON文件路徑
        """
        try:
            # 創建輸出文件夾
            os.makedirs("output", exist_ok=True)
            
            # 準備JSON數據
            set_index_flag = False
            if 'Index' not in self.data.columns:
                self.data = self.data.reset_index('Index')
                set_index_flag = True 
            json_data = []
            for _, row in self.data.iterrows():
                item = {
                    'Index': int(row['Index']),
                    'Title': row['Title'],
                    'Directed_Index': [int(x) for x in row['Directed_Index']]
                }
                # 如果存在瀏覽量數據，也加入
                if 'views' in row:
                    item['views'] = row['views']
                json_data.append(item)
            
            # 安全地寫入主要數據文件
            json_path = f"output/{prefix}.json"
            self.safe_write_json(json_data, json_path)
            
            # 安全地寫入已處理條目緩存
            processed_path = "output/processed_titles_cache.json"
            self.safe_write_json(list(self.processed_titles), processed_path)
            
            if set_index_flag:
                self.data.set_index('Index')

            print(f"數據已安全保存為:")
            print(f"- JSON: {json_path}")
            print(f"- 已處理條目緩存: {processed_path}")
            
            return json_path
            
        except Exception as e:
            print(f"保存文件時發生錯誤: {str(e)}")
            traceback.print_exc()
            return None
    
    def save_batch_pageviews(self, titles, startDate, endDate, batch_size=100):
        """
        批次獲取並保存多個條目的瀏覽量歷史
        
        參數:
            titles (list): 維基百科條目標題列表
            startDate (str): 開始日期，格式為 'YYYYMMDD'
            endDate (str): 結束日期，格式為 'YYYYMMDD'
            batch_size (int): 每批處理的條目數量
            
        返回:
            tuple: (成功數量, 失敗數量)
        """
        success_count = 0
        fail_count = 0
        
        try:
            # 批次處理條目
            updates = {}  # 用於存儲需要更新的數據
            
            for title in tqdm(titles, desc="獲取瀏覽量數據"):
                # 使用緩存檢查是否已處理
                if title in self.views_cache:
                    print(f"條目 '{title}' 的瀏覽量數據已存在於緩存中，跳過")
                    continue
                
                # 獲取瀏覽量數據
                df = self.get_pageviewHistory(title, startDate, endDate, granularity="monthly")
                
                if not df.empty:
                    # 直接更新 DataFrame
                    idx = self.data[self.data['Title'] == title].index
                    if len(idx) > 0:
                        self.data.at[idx[0], 'views'] = df.values.tolist()
                        self.views_cache.add(title)
                        success_count += 1
                else:
                    fail_count += 1
                
                # 當累積足夠的更新數據時，執行批次保存
                if success_count % batch_size == 0:
                    # 保存整個 DataFrame 到 JSON
                    self.save_to_files()
                    # 保存緩存
                    self.safe_write_json(list(self.views_cache), self.views_cache_file)
                    print(f"已保存一批數據，目前已處理 {success_count} 個條目")
                
                time.sleep(0.1)  # 避免請求過於頻繁
            
            # 處理剩餘的更新
            if success_count % batch_size != 0:
                self.save_to_files()
                self.safe_write_json(list(self.views_cache), self.views_cache_file)
                print(f"已保存最後一批數據，總共處理 {success_count} 個條目")
            
            return success_count, fail_count
                
        except Exception as e:
            print(f"批次處理瀏覽量數據時發生錯誤: {str(e)}")
            traceback.print_exc()
            return success_count, fail_count
    
    def save_pageview(self, title, startDate, endDate):
        """
        獲取條目的瀏覽量歷史並安全地保存到 JSON 文件中
        
        參數:
            title (str): 維基百科條目標題
            startDate (str): 開始日期，格式為 'YYYYMMDD'
            endDate (str): 結束日期，格式為 'YYYYMMDD'
            
        返回:
            bool: 保存是否成功
        """
        if builder.data[builder.data['Title'] == title]['views'].notna().any():
            print(f"條目 '{title}' 的瀏覽量數據已存在，跳過保存")
            return False
        try:
            # 獲取瀏覽量數據
            df = self.get_pageviewHistory(title, startDate, endDate, granularity="monthly")
            
            if df.empty:
                print(f"警告：無法獲取 '{title}' 的瀏覽量數據")
                return False
            
            # 將數據轉換為所需格式
            views_data = df.values.tolist()
            
            # 找到對應條目的索引
            if title in self.title_to_index:
                json_path = "output/wiki_network.json"
                
                # 讀取現有的JSON文件
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                except Exception as e:
                    print(f"讀取JSON文件時發生錯誤: {str(e)}")
                    return False
                
                # 更新數據
                for item in json_data:
                    if item['Title'] == title:
                        item['views'] = views_data
                        break
                
                # 安全地寫入更新後的數據
                try:
                    self.safe_write_json(json_data, json_path)
                    print(f"成功保存 '{title}' 的瀏覽量數據")
                    return True
                except Exception as e:
                    print(f"寫入JSON文件時發生錯誤: {str(e)}")
                    return False
            
            else:
                print(f"錯誤：找不到條目 '{title}'")
                return False
                
        except Exception as e:
            print(f"保存瀏覽量數據時發生錯誤: {str(e)}")
            traceback.print_exc()
            return False

    def build_imp_network_with_redirect(self, output_path='output/imp_network_with_redirect.json'):
        index_to_title = dict(zip(self.data['Index'], self.data['Title']))
        # 確保 DataFrame 以 Title 為 index
        if self.data.index.name != 'Title':
            self.data = self.data.set_index('Title')
        # 1. 收集 imp_data 節點
        imp_titles = set(self.imp_data['Title'])
        all_titles = set(imp_titles)
        imp_indices = set(self.imp_data['Index'])
        print(f"節點數量: {len(all_titles)}")

        # 2. 單層 redirect 處理
        def resolve_redirect(title):
            return self.redirect_cache.get(title, title)

        # 3. 建立 {最終標題: [所有來源標題]}
        redirect_groups = {}
        for title in all_titles:
            final_title = resolve_redirect(title)
            redirect_groups.setdefault(final_title, set()).add(title)

        # 4. 產生新節點
        new_nodes = []
        for final_title, source_titles in redirect_groups.items():
            if final_title not in self.data.index:
                continue
            idx = self.data.loc[final_title, 'Index']
            # 合併 Directed_Index
            directed_set = set()
            views_list = []
            for src_title in source_titles:
                if src_title in self.data.index:
                    src_row = self.data.loc[src_title]
                    directed_set.update(src_row['Directed_Index'])
                    if 'views' in src_row and isinstance(src_row['views'], list):
                        views_list.extend(src_row['views'])
            # 去重 views
            if views_list:
                views_list = list({(v[0], v[1]) for v in views_list if isinstance(v, (list, tuple)) and len(v) == 2})
                views_list.sort()
            # 處理 Directed_Index 也要經過單層 redirect
            new_directed = []
            for link_idx in directed_set:
                # 這裡要反查 index->title
                if link_idx not in imp_indices:
                    continue
                else:
                    link_title = index_to_title[link_idx]
                    link_title = resolve_redirect(link_title)
                    if link_title in self.data.index:
                        new_idx = self.data.loc[link_title, 'Index']
                        if new_idx != idx:  # 避免自環
                            new_directed.append(new_idx)
            node = {
                'Index': int(idx),
                'Title': final_title,
                'Directed_Index': sorted(set(int(i) for i in new_directed))
            }
            if views_list:
                node['views'] = views_list
            new_nodes.append(node)

        # 5. 輸出
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(new_nodes, f, ensure_ascii=False, indent=2)
        print(f"已輸出新網絡至 {output_path}")

def sync_two_df_directed_Index(df1=pd.DataFrame(),df2=pd.DataFrame(),titles= list()):
    '''
    把df2中，相同title的directed_index，同步到df1中
    '''
    if not isinstance(titles,list):
        raise ValueError('titles不是list')
    if not isinstance(df1,pd.DataFrame):
        raise ValueError('df1不是pd.DataFrame')
    if not isinstance(df2,pd.DataFrame):
        raise ValueError('df2不是pd.DataFrame')
    if 'Directed_Index' not in df1.columns:
        raise ValueError('df1沒有Directed_Index')
    if 'Directed_Index' not in df2.columns:
        raise ValueError('df2沒有Directed_Index')
    if 'Title' not in df1.columns:
        raise ValueError('df1沒有Title')
    if 'Title' not in df2.columns:
        raise ValueError('df2沒有Title')

    df1 = df1.copy()
    df2 = df2.copy()

    df1.set_index('Title',inplace=True)
    df2.set_index('Title',inplace=True)
    for title in titles:
        set1 = set(df1.loc[title,'Directed_Index'])
        set2 = set(df2.loc[title,'Directed_Index'])
        df1.at[title,'Directed_Index'] = list(set1 | set2)
        df2.at[title,'Directed_Index'] = list(set1 | set2)
    df1.reset_index(inplace=True)
    df2.reset_index(inplace=True)
    print(f'同步完成')
    return df1,df2

def get_safe_data(safe_data_file='output/safe/imp_network_with_redirect.json'):
    safe_data = []
    if os.path.exists(safe_data_file):
        with open(safe_data_file, 'r', encoding='utf-8') as f:
            for item in ijson.items(f, 'item'):
                # 根據需要保留欄位，例如只保留 Index, Title, Directed_Index
                safe_data.append({
                    'Index': item.get('Index'),
                    'Title': item.get('Title'),
                    'Directed_Index': item.get('Directed_Index'),
                    'Views': item.get('Views')
                })
        safe_data = pd.DataFrame(safe_data)
        print(f"已篩選出 {len(safe_data)} 個安全條目")
    return safe_data

def process_imp_data(imp_data,unprocessed_titles):
    imp_data = imp_data.copy()
    valid_titles = set(imp_data['Title'])
    imp_data.set_index('Title',inplace=True)
    for title in unprocessed_titles:
        if title in valid_titles:
            links_titles = builder.get_article_links(title)
        directed_index = []
        for link_title in links_titles:
            if link_title in valid_titles:
                directed_index.append(imp_data.loc[link_title, 'Index'])
        
        imp_data.at[title, 'Directed_Index'] = directed_index
    imp_data.reset_index(inplace=True)
    return imp_data

if __name__ == "__main__":
    # 初始化構建器
    builder = WikiNetworkBuilder(user_agent='IlyaForLessonResearch (b10202052@ntu.edu.tw)',load_file='output/wiki_network.json')
