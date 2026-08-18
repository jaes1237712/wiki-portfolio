import pandas as pd
import time
import json
import os
from tqdm import tqdm
import numpy as np
import networkx as nx  # 添加 networkx 引入
from datetime import datetime, timedelta
import traceback
import matplotlib.pyplot as plt
from pathlib import Path
from sentence_transformers import SentenceTransformer
import pickle
import torch
import igraph as ig
import infomap

'''
DATA JSON文件結構，記錄維基百科條目的資訊
{   
    "Index": int,
    "Title": str,                           #條目名稱
    "Directed_Index": list of int,          #連結的條目Index
    "Views": list of [date(str), views(int)]     #條目在那個月的瀏覽量，格式為'YYYY-MM-01'例如:2025-03-01
}
'''

'''
igraph的屬性
        vertex properties:
            idx: int (should not be float) # article_id
            title: str
            tag: json string -> set()              #hub, authority, bridge, ...
            community: int (should not be float)   # two-level community
            community_path: json string -> tuple(int) # multi-level community path
            flow: float
            community_level_1~n: int (should not be float) # multi-level community level
        es properties:
            weight: float (to vertex normalization)
'''

'''
Subgraph的特殊節點
Hub: 每個子圖最高Hub score的節點
Authority: 每個子圖最高Authority score的節點
Bridge: 每個子圖中，向外連結最多的節點
'''

class WikiNetwork:
    def __init__(self, graph_dir='last_graph_data',data_file='output/imp_network_with_redirect.json',embeddings_dir='output/embeddings',json_dir='last_json_data'):
        '''
        命名邏輯：
            G開頭為graph
            路徑則以file或dir開頭（待實施）
            _list為list of graph
            _relation為社群關係簡化圖
            _effective為有效子圖 (節點數量介於特定值之間)
            _subgraph為大圖(self.G)的子圖，但有規範新的attribute
            _community為社群
            _partition為社群分割
        '''
        # 源頭數據
        self.G = None
        self.data = None
        # two level
        '''
        effective: 社群節點數量介於min~max之間 （尚未決定）
        '''
        self.G_two_level_community_relation = None                  # 兩層社群關係簡化圖，每個社群只有三個節點
        self.G_list_two_level_effective_subgraphs = None                 # file path: graph_dir/two_level_subgraphs
        self.two_level_special_nodes = None                          # 每個子圖的特殊節點
        self.codelength_two_level = None
        self.two_level_effective_community = None                    # 有效社群 like 社群1,2,3: [1,2,3]
        # Multi-level
        '''
        收錄所有子圖，不管節點數量
        '''
        self.im = None                                  # infomap object
        self.G_multi_level_1_community_relation = None          # 一階社群關係簡化圖，每個社群只有三個節點
        self.G_multi_level_2_community_relation = None          # 二階社群關係簡化圖，每個社群只有三個節點
        self.G_multi_level_3_community_relation = None          # 三階社群關係簡化圖，每個社群只有三個節點
        self.G_list_multi_level_1_subgraphs = None                  # 取所屬葉節點的子圖，file name: graph_dir/multi_level_1_subgraphs/subgraph_0.graphml
        self.G_list_multi_level_2_subgraphs = None                  # 取所屬葉節點的子圖，file name: graph_dir/multi_level_2_subgraphs/subgraph_0_1.graphml
        self.G_list_multi_level_3_subgraphs = None                  # 取所屬葉節點的子圖，file name: graph_dir/multi_level_3_subgraphs/subgraph_0_1_2.graphml
        self.codelength_multi_level = None

        # IO 
        self.embeddings_dir = embeddings_dir
        self.data_file = data_file
        self.graph_dir = graph_dir
        self.two_level_dir = f"{graph_dir}/two_level_subgraphs"
        self.multi_level_1_dir = f"{graph_dir}/multi_level_subgraphs_level_1"
        self.multi_level_2_dir = f"{graph_dir}/multi_level_subgraphs_level_2"
        self.multi_level_3_dir = f"{graph_dir}/multi_level_subgraphs_level_3"
        self.json_dir = json_dir
        self.two_level_json_dir = f"{json_dir}/two_level_subgraphs"
        self.multi_level_1_json_dir = f"{json_dir}/multi_level_subgraphs_level_1"
        self.multi_level_2_json_dir = f"{json_dir}/multi_level_subgraphs_level_2"
        self.multi_level_3_json_dir = f"{json_dir}/multi_level_subgraphs_level_3"
        # dict
        self.embeddings_dict = None
        self.indices_embeddings = None
        self.title_to_index = None
        self.index_to_title = None
        self._index_to_vertex = None
        self._vertex_to_index = None
    
    def check_graph_data_and_folder(self):
        '''
        檢查圖形數據是否完整，如果完整則回傳True，否則回傳False
        '''
        flag = True
        if self.G is None:
            print("self.G is None")
            flag = False
        if self.G_two_level_community_relation is None:
            print("self.G_two_level_community_relation is None")
            flag = False
        if self.G_list_two_level_effective_subgraphs is None:
            print("self.G_list_two_level_effective_subgraphs is None")
            flag = False
        if self.G_multi_level_1_community_relation is None:
            print("self.G_multi_level_1_community_relation is None")
            flag = False
        if self.G_multi_level_2_community_relation is None:
            print("self.G_multi_level_2_community_relation is None")
            flag = False
        if self.G_multi_level_3_community_relation is None:
            print("self.G_multi_level_3_community_relation is None")
            flag = False
        if self.G_list_multi_level_1_subgraphs is None:
            print("self.G_list_multi_level_1_subgraphs is None")
            flag = False
        if self.G_list_multi_level_2_subgraphs is None:
            print("self.G_list_multi_level_2_subgraphs is None")
            flag = False
        if self.G_list_multi_level_3_subgraphs is None:
            print("self.G_list_multi_level_3_subgraphs is None")
            flag = False
        if not os.path.exists(self.graph_dir):
            os.makedirs(self.graph_dir)
        if not os.path.exists(self.two_level_dir):
            os.makedirs(self.two_level_dir)
        if not os.path.exists(self.multi_level_1_dir):
            os.makedirs(self.multi_level_1_dir)
        if not os.path.exists(self.multi_level_2_dir):
            os.makedirs(self.multi_level_2_dir)
        if not os.path.exists(self.multi_level_3_dir):
            os.makedirs(self.multi_level_3_dir)

        return flag

    def save_graph_data(self):
        '''
        保存圖形數據:
        self.G: 完整圖形
        self.G_two_level_subgraphs: 有效子圖列表
        self.subgraph_connection_matrix: 子圖連接矩陣        
        '''
        try:
            self.check_graph_data_and_folder()
            # self.G
            graph_utils.write_graphML(self.G, f"{self.graph_dir}/graph.graphml")
            
            # two-level
            if self.G_list_two_level_effective_subgraphs is not None:
                for file_name in os.listdir(self.two_level_dir):
                    if file_name.startswith('subgraph_'):
                        os.remove(f"{self.two_level_dir}/{file_name}")
                for subgraph in self.G_list_two_level_effective_subgraphs:
                    community = subgraph.vs[0]['community']
                    file_name = f"{self.two_level_dir}/subgraph_{int(community)}.graphml"
                    graph_utils.write_graphML(subgraph, file_name)
            
            graph_utils.write_graphML(self.G_two_level_community_relation, f"{self.graph_dir}/two_level_community_relation.graphml")

            # multi-level
            # Level 1
            if self.G_list_multi_level_1_subgraphs is not None:
                for file_name in os.listdir(self.multi_level_1_dir):
                    if file_name.startswith('subgraph_'):
                        os.remove(f"{self.multi_level_1_dir}/{file_name}")
                for subgraph in self.G_list_multi_level_1_subgraphs:
                    subgraph_path = list(int(i) for i in subgraph.vs[0]['community_path'])
                    if len(subgraph_path) > 0:
                        file_name = f"{self.multi_level_1_dir}/subgraph_{subgraph_path[0]}.graphml"
                        graph_utils.write_graphML(subgraph, file_name)
                    else:
                        raise ValueError("len(subgraph_path) should greater than 0")
                
            # Level 2
            if self.G_list_multi_level_2_subgraphs is not None:
                for file_name in os.listdir(self.multi_level_2_dir):
                    if file_name.startswith('subgraph_'):
                        os.remove(f"{self.multi_level_2_dir}/{file_name}")
                for subgraph in self.G_list_multi_level_2_subgraphs:
                    subgraph_path = list(int(i) for i in subgraph.vs[0]['community_path'])
                    if len(subgraph_path) > 1:
                        file_name = f"{self.multi_level_2_dir}/subgraph_{subgraph_path[0]}_{subgraph_path[1]}.graphml"
                        graph_utils.write_graphML(subgraph, file_name)
                    else:
                        raise ValueError("len(subgraph_path) should greater than 1")
                
            # Level 3
            if self.G_list_multi_level_3_subgraphs is not None:
                for file_name in os.listdir(self.multi_level_3_dir):
                    if file_name.startswith('subgraph_'):
                        os.remove(f"{self.multi_level_3_dir}/{file_name}")
                for subgraph in self.G_list_multi_level_3_subgraphs:
                    subgraph_path = list(int(i) for i in subgraph.vs[0]['community_path'])
                    if len(subgraph_path) > 2:
                        file_name = f"{self.multi_level_3_dir}/subgraph_{subgraph_path[0]}_{subgraph_path[1]}_{subgraph_path[2]}.graphml"
                        graph_utils.write_graphML(subgraph, file_name)
                    else:
                        raise ValueError("len(subgraph_path) should greater than 2")
                
            graph_utils.write_graphML(self.G_multi_level_1_community_relation, f"{self.graph_dir}/multi_level_1_community_relation.graphml")
            graph_utils.write_graphML(self.G_multi_level_2_community_relation, f"{self.graph_dir}/multi_level_2_community_relation.graphml")
            graph_utils.write_graphML(self.G_multi_level_3_community_relation, f"{self.graph_dir}/multi_level_3_community_relation.graphml")
            if self.im is not None:
                self.im.write_flow_tree(f"{self.graph_dir}/flow_tree.tree")

            print(f"社群數據已保存至 {self.graph_dir}")
            return True
            
        except Exception as e:
            print(f"保存社群數據時發生錯誤: {str(e)}")
            traceback.print_exc()
            return False

    def save_json(self):
        '''
        save two-level effective subgraphs to json file
        '''
        if self.G_list_two_level_effective_subgraphs is not None:
            for subgraph in self.G_list_two_level_effective_subgraphs:
                graph_utils.write_json(subgraph, f"{self.two_level_json_dir}/subgraph_{int(subgraph.vs[0]['community'])}.json")
        if self.G_two_level_community_relation is not None:
            graph_utils.write_json(self.G_two_level_community_relation, f'{self.json_dir}/two_level_community_relation.json')
        print('save json to ', self.two_level_json_dir)
        return True

    def load_exist_graph(self):
        """
        從檔案載入大圖G、社群關係簡化圖G_community_relation、子圖列表G_subgraphs的數據
        graphML file:
            vertex properties:
                idx: int
                title: str
                tag: json string -> set()
                community: int
                community_path: json string -> tuple(int)
                flow: float
                community_level_1~n: int
            edge properties:
                source: int (idx)
                target: int (idx)
                weight: float (to vertex normalization)                
        """
        self.check_graph_data_and_folder()  # only for check file folder exist
        # self.G
        self.G = graph_utils.read_graphML(f"{self.graph_dir}/graph.graphml")['graph']
        # two-level
        self.G_two_level_community_relation = graph_utils.read_graphML(f"{self.graph_dir}/two_level_community_relation.graphml")['graph']
        self.G_list_two_level_effective_subgraphs = []
        self.two_level_effective_community = []
        for file_name in os.listdir(self.two_level_dir):
            if file_name.startswith('subgraph_'):
                if file_name.endswith('.graphml'):
                    subgraph = graph_utils.read_graphML(f"{self.two_level_dir}/{file_name}")['graph']
                    commuity = subgraph.vs[0]['community']
                    self.G_list_two_level_effective_subgraphs.append(subgraph)
                    self.two_level_effective_community.append(commuity)
                else:
                    raise ValueError(f"file {file_name} is not a graphml file")
        # multi-level
        self.G_multi_level_1_community_relation = graph_utils.read_graphML(f"{self.graph_dir}/multi_level_1_community_relation.graphml")['graph']
        self.G_multi_level_2_community_relation = graph_utils.read_graphML(f"{self.graph_dir}/multi_level_2_community_relation.graphml")['graph']
        self.G_multi_level_3_community_relation = graph_utils.read_graphML(f"{self.graph_dir}/multi_level_3_community_relation.graphml")['graph']
        self.G_list_multi_level_1_subgraphs = []
        self.G_list_multi_level_2_subgraphs = []
        self.G_list_multi_level_3_subgraphs = []
        for file_name in os.listdir(self.multi_level_1_dir):
            if file_name.startswith('subgraph_'):
                if file_name.endswith('.graphml'):
                    subgraph = graph_utils.read_graphML(f"{self.multi_level_1_dir}/{file_name}")['graph']
                    self.G_list_multi_level_1_subgraphs.append(subgraph)
        for file_name in os.listdir(self.multi_level_2_dir):
            if file_name.startswith('subgraph_'):
                if file_name.endswith('.graphml'):
                    subgraph = graph_utils.read_graphML(f"{self.multi_level_2_dir}/{file_name}")['graph']
                    self.G_list_multi_level_2_subgraphs.append(subgraph)
        for file_name in os.listdir(self.multi_level_3_dir):
            if file_name.startswith('subgraph_'):
                if file_name.endswith('.graphml'):
                    subgraph = graph_utils.read_graphML(f"{self.multi_level_3_dir}/{file_name}")['graph']
                    self.G_list_multi_level_3_subgraphs.append(subgraph)
            
    def load_data(self):
        """
        將維基百科JSON數據載入到DataFrame中
        回傳dataframe
        """
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            self.data = pd.DataFrame(json_data)
            self.title_to_index = dict(zip(self.data['Title'], self.data['Index']))
            self.index_to_title = dict(zip(self.data['Index'], self.data['Title']))
            return True
        return False
    
    def create_network(self, all_directed_indices_in_data=False):
        """
        從 DataFrame 網絡數據創建有向圖
        
        參數:
            all_directed_indices_in_data (bool): 是否所有連結的目標節點都在數據中
        返回:
            igraph.Graph: igraph有向圖對象
        """
        if self.data is None:
            raise ValueError("請先載入數據")
        self.G = self._load_network(all_directed_indices_in_data)
        return self.G

    def _load_network(self, all_directed_indices_in_data = True):
        """
        從 DataFrame 載入網絡數據並創建有向圖
        
        參數:
            self.data (pd.DataFrame): 包含網絡數據的DataFrame，必須包含 'Index', 'Title', 'Directed_Index' 列
            all_directed_indices_in_data (bool): 是否所有連結的目標節點都在數據中
            
        返回:
            igraph.Graph: igraph有向圖對象
        """
        try:
            if self.data is None:
                raise ValueError("請先載入數據")

            
            # 創建有向圖
            G = ig.Graph(directed=True)
            
            # 獲取所有有效的節點索引集合
            valid_indices_list = self.data['Index'].tolist() # 創建列表以加速索引查找
            self.index_to_vertex = {idx: i for i, idx in enumerate(valid_indices_list)}  # 創建索引映射
            self.vertex_to_index = {i: idx for idx, i in self.index_to_vertex.items()}  # vertex_id -> index
            valid_indices = set(valid_indices_list)  # 使用集合加速查找
            # 添加節點
            print("添加節點...")
            G.add_vertices(len(valid_indices_list))
            G.vs["idx"] = valid_indices_list  # 使用Index作為idx屬性
            G.vs["title"] = self.data['Title'].tolist()  # 添加Title屬性
            G.vs["tag"] = [set() for _ in range(len(valid_indices_list))]

            # 預先分配邊列表
            print("收集邊...")
            edges = []
            edges_count = 0
            invalid_edges = 0
            
            # 使用向量化操作處理邊
            if all_directed_indices_in_data:
                tmp = 1000
                # 如果所有目標節點都在數據中，可以直接處理
                for _, row in self.data.iterrows():
                    source_vertex = self.index_to_vertex[row['Index']]
                    for target_vertex in row['Directed_Index']:
                        edges.append((source_vertex, self.index_to_vertex[target_vertex]))
                    edges_count += len(row['Directed_Index'])
                if edges_count > tmp:
                    print(f"當前邊數量: {edges_count}")
                    tmp += 5000
            else:
                # 需要檢查目標節點是否有效
                for _, row in self.data.iterrows():
                    tmp = 1000
                    source_vertex = self.index_to_vertex[row['Index']]
                    for target in row['Directed_Index']:
                        if target in valid_indices:
                            edges.append((source_vertex, self.index_to_vertex[target]))
                            edges_count += 1
                        else:
                            invalid_edges += 1
                    if edges_count > tmp:
                        print(f"當前邊數量: {edges_count}")
                        tmp += 5000
            
            # 一次性批量添加所有邊
            print("添加邊...")
            G.add_edges(edges)
            
            # 刪除自環
            G.simplify(multiple=True, loops=True)
            
            print(f"\n成功創建網絡：")
            print(f"- {G.vcount()} 個節點")
            print(f"- {G.ecount()} 條有效邊")
            print(f"- 忽略了 {invalid_edges} 條無效邊（目標節點不在原始數據中）")
            
            return G
            
        except Exception as e:
            print(f"創建網絡時發生錯誤: {str(e)}")
            traceback.print_exc()
            return None 


def config_weight_topology(wiki: WikiNetwork):
    """
    為圖中的邊添加權重
    """
    if wiki.G is None:
        raise ValueError("請先創建網絡")
    
    # 添加邊的權重
    tmp = 5000
    cnt = 0
    total_edges = wiki.G.ecount()
    for edge in wiki.G.es:
        edge['weight'] =graph_utils.get_similarity_topology(wiki.G ,edge.source, edge.target)
        cnt +=1
        if cnt > tmp:
            print(f"num of weighted edges: {cnt}/{total_edges}")
            tmp += 5000
    print("邊的權重已添加")

def config_infomap(wiki: WikiNetwork,trails=5):
    """
    使用Infomap算法進行社群檢測
    """
    if wiki.G is None:
        raise ValueError("請先創建網絡")
    
    # 使用Infomap算法進行社群檢測 im表示為infomap物件
    im_two_level_partition = wiki.G.community_infomap(edge_weights=wiki.G.es['weight'],trials=trails)
    wiki.G.vs['community'] = im_two_level_partition.membership 
    wiki.G.vs['community'] = [int(i) for i in wiki.G.vs['community']]
    tmp = set(wiki.G.vs['community'])
    wiki.two_level_effective_community = []
    config_G_list_two_level_effective_subgraphs(wiki)
    # 印出每個子圖的節點數 histogram
    node_nums = [subgraph.vcount() for subgraph in wiki.G_list_two_level_effective_subgraphs]
    q1, q3 = np.percentile(node_nums, [25, 75])
    filtered_nums = [n for n in node_nums if q1 <= n <= q3]
    plt.hist(filtered_nums, bins=100)
    plt.show()
    print('node_nums_histogram: between 25 and 75 percentile')
    wiki.codelength_two_level = im_two_level_partition.codelength
    
    print(f"Detected finished {len(wiki.two_level_effective_community)} effective communities")

def config_G_list_two_level_effective_subgraphs(wiki: WikiNetwork, max_node_num=500, min_node_num=50):
    """
    創建有效子圖（社群中節點數量在max_node_num和min_node_num之間）
    vertex attribute: idx, community, tag, flow, title, betweenness    #tag要放什麼還不知道
    edge attribute: source_idx, target_idx ,betweenness
    """
    # 獲取有效社群的索引
    if wiki.G.vs['community'] is None:
        raise ValueError("請先創建社群")
    wiki.two_level_effective_community = []
    tmp = set(wiki.G.vs['community'])
    two_level_partition = [[] for _ in range(len(tmp))]
    for i in range(len(tmp)):
        two_level_partition[i] = wiki.G.vs.select(community=i)
    for i, community in enumerate(two_level_partition):
        if len(community) > min_node_num and len(community) <= max_node_num:
            wiki.two_level_effective_community.append(i)
    wiki.G_list_two_level_effective_subgraphs = []
    for i in wiki.two_level_effective_community:
        subgraph = wiki.G.subgraph(two_level_partition[i])
        # vertex attribute: idx, community, tag, flow, title
        flow = subgraph.pagerank(directed=True, weights='weight')
        subgraph.vs['flow'] = flow
        betweenness = subgraph.betweenness()
        subgraph.vs['betweenness'] = betweenness
        for attr in subgraph.vs.attributes():
            if attr not in ['idx', 'community', 'tag', 'flow', 'title', 'betweenness']:
                del subgraph.vs[attr]
        if 'tag' not in subgraph.vs.attributes():
            subgraph.vs['tag'] = [set() for _ in range(subgraph.vcount())]
        # edge attribute: source_idx, target_idx ,betweenness
        betweenness = subgraph.edge_betweenness()
        for edge in subgraph.es:
            edge['source_idx'] = edge.source_vertex['idx']
            edge['target_idx'] = edge.target_vertex['idx']
            edge['betweenness'] = betweenness[edge.index]
        for attr in subgraph.es.attributes():
            if attr not in ['source_idx', 'target_idx', 'betweenness']:
                del subgraph.es[attr]
        wiki.G_list_two_level_effective_subgraphs.append(subgraph)
    print(f"Detected finished {len(wiki.two_level_effective_community)} effective communities")

def config_two_level_special_nodes(wiki: WikiNetwork):
    '''
    Effective Subgraph的特殊節點
    Hub: 每個子圖最高Hub score的節點
    Authority: 每個子圖最高Authority score的節點
    Two_level_Center: 每個子圖中，betweenness最高的節點
    Bridge: 每個子圖中，向外連結最多的節點
    '''
    wiki.two_level_special_nodes = set()                  # 儲存igraph vertex物件
    if wiki.G_list_two_level_effective_subgraphs is None:
        raise ValueError("請先創建有效子圖")
    if 'tag' not in wiki.G_list_two_level_effective_subgraphs[0].vs.attributes():
        for i in range(len(wiki.G_list_two_level_effective_subgraphs)):
            wiki.G_list_two_level_effective_subgraphs[i].vs['tag'] = [set() for _ in range(wiki.G_list_two_level_effective_subgraphs[i].vcount())]

    for i,subgraph in enumerate(wiki.G_list_two_level_effective_subgraphs):
        hub_scores = subgraph.hub_score()
        authority_scores = subgraph.authority_score()
        betweenness_scores = subgraph.betweenness()
        exit_edges_num = []
        for node in subgraph.vs:
            exit_edges_num.append(len(wiki.G.vs.select(idx=node['idx'])[0].out_edges()) - len(node.out_edges()))
        # 找出每個子圖的最高Hub score的節點
        max_hub_node = np.argmax(hub_scores)
        max_authority_node = np.argmax(authority_scores)
        max_betweenness_node = np.argmax(betweenness_scores)
        max_exit_edges_node = np.argmax(exit_edges_num)
        wiki.G_list_two_level_effective_subgraphs[i].vs[max_hub_node]['tag'].add('hub')
        wiki.G_list_two_level_effective_subgraphs[i].vs[max_authority_node]['tag'].add('authority') 
        wiki.G_list_two_level_effective_subgraphs[i].vs[max_betweenness_node]['tag'].add('two_level_center')
        wiki.G_list_two_level_effective_subgraphs[i].vs[max_exit_edges_node]['tag'].add('bridge')
        wiki.two_level_special_nodes.add(wiki.G_list_two_level_effective_subgraphs[i].vs[max_hub_node])
        wiki.two_level_special_nodes.add(wiki.G_list_two_level_effective_subgraphs[i].vs[max_authority_node])
        wiki.two_level_special_nodes.add(wiki.G_list_two_level_effective_subgraphs[i].vs[max_betweenness_node])
        wiki.two_level_special_nodes.add(wiki.G_list_two_level_effective_subgraphs[i].vs[max_exit_edges_node])
    print(f"Detected finished {len(wiki.two_level_special_nodes)} special nodes")

def config_G_two_level_community_relation(wiki: WikiNetwork):
    '''
    創建社群關係簡化圖
    vertex : authority, hub, bridge, two_level_center for each community 
    edge(only inter-community) : community_1_bridge -> community_2_bridge

    vertex_attributes: idx, community, tag, flow, title, betweenness
                        flow: pagerank in the new graph
                        betweenness: vertex betweenness in the new graph
    edge_attributes: source_idx, target_idx ,betweenness, connections_num, distance
                        connections_num: number of connections between two communities (bridge)
                        betweenness: edge betweenness in the new graph
                        distance: distance between two communities (two_level_center) -> shortest path in wiki.G
    '''

    if wiki.two_level_special_nodes is None:
        raise ValueError("please create special nodes")
    wiki.G_two_level_community_relation = ig.Graph(directed=True)
    not_bridge_nodes = [node for node in wiki.two_level_special_nodes if 'bridge' not in node['tag']]
    # 建立只有bridge vertex的graph
    for node in wiki.two_level_special_nodes:
        # 先新增node有idx, community, tag, title 屬性，之後再計算flow, betweenness
        attrs = {
            'idx': node['idx'],
            'community': node['community'],
            'tag': node['tag'],
            'title': node['title']
        }
        if 'bridge' in node['tag']:
            wiki.G_two_level_community_relation.add_vertex(**attrs)
    # add edge
    bridge_nodes = [v for v in wiki.G_two_level_community_relation.vs if 'bridge' in v['tag']]
    for bridge_node1 in bridge_nodes:
        for bridge_node2 in bridge_nodes:
            if bridge_node1['idx'] != bridge_node2['idx']:
                attrs = {
                    'source_idx': bridge_node1['idx'],
                    'target_idx': bridge_node2['idx']
                }
                wiki.G_two_level_community_relation.add_edge(bridge_node1.index, bridge_node2.index, **attrs)
    # calculate connections_num in wiki.G
    community = set(wiki.G_two_level_community_relation.vs['community'])
    max_community = max(community)
    connections_matrix = np.zeros((max_community+10,max_community+10))
    for node in wiki.G.vs:
        source_comm = node['community']
        if source_comm not in community:
            continue
        for edge in node.out_edges():
            target_comm = edge.target_vertex['community']
            if target_comm not in community:
                continue
            if source_comm != target_comm:
                connections_matrix[source_comm][target_comm] += 1
    for edge in wiki.G_two_level_community_relation.es:
        source_comm = edge.source_vertex['community']
        target_comm = edge.target_vertex['community']
        edge['connections_num'] = connections_matrix[source_comm][target_comm]
    # calculate vertex flow, betweenness in wiki.G_two_level_community_relation
    tmp_graph = wiki.G_two_level_community_relation.copy()
    for node in not_bridge_nodes:
        # 先新增node有idx, community, tag, title 屬性，之後再計算flow, betweenness
        attrs = {
            'idx': node['idx'],
            'community': node['community'],
            'tag': node['tag'],
            'title': node['title']
        }
        tmp_graph.add_vertex(**attrs)
    # distance: shortest path in wiki.G between two communities (two_level_center)
    distance_matrix = np.zeros((max_community+10,max_community+10))
    for i in range(max_community+10):
        for j in range(max_community+10):
            if i != j and connections_matrix[i][j] > 0:
                nodes1 = tmp_graph.vs.select(community=i)
                nodes2 = tmp_graph.vs.select(community=j)
                for node1 in nodes1:
                    if 'two_level_center' in node1['tag']:
                        idx1 = node1['idx']
                        break
                for node2 in nodes2:
                    if 'two_level_center' in node2['tag']:
                        idx2 = node2['idx']
                        break
                index1 = wiki.G.vs.select(idx=idx1)[0].index
                index2 = wiki.G.vs.select(idx=idx2)[0].index
                distance_matrix[i][j] = len(wiki.G.get_shortest_path(index1,index2)) - 1
    for edge in wiki.G_two_level_community_relation.es:
        source_comm = edge.source_vertex['community']
        target_comm = edge.target_vertex['community']
        if connections_matrix[source_comm][target_comm] == 0:
            edge['distance'] = np.inf
        else:
            edge['distance'] = distance_matrix[source_comm][target_comm]
    wiki.G_two_level_community_relation.vs['flow'] = wiki.G_two_level_community_relation.pagerank(directed=True, weights=wiki.G_two_level_community_relation.es['connections_num'])
    wiki.G_two_level_community_relation.vs['betweenness'] = wiki.G_two_level_community_relation.betweenness(directed=True, weights=wiki.G_two_level_community_relation.es['distance'])
    # calculate edge betweenness in wiki.G_two_level_community_relation8
    wiki.G_two_level_community_relation.es['betweenness'] = wiki.G_two_level_community_relation.edge_betweenness(directed=True, weights=wiki.G_two_level_community_relation.es['distance'])
    need_add_attrs = []
    for node in not_bridge_nodes:
        # 選一個community一樣的節點
        friend_node = wiki.G_two_level_community_relation.vs.select(community=node['community'])[0]
        attrs = {
            'idx': node['idx'],
            'community': node['community'],
            'tag': node['tag'],
            'title': node['title'],
            'flow': friend_node['flow'],
            'betweenness': friend_node['betweenness']
        }
        need_add_attrs.append(attrs)
    for attr in need_add_attrs:
        wiki.G_two_level_community_relation.add_vertex(**attr)
    
    print(f"Detected finished {len(wiki.G_two_level_community_relation.vs)} vertices and {len(wiki.G_two_level_community_relation.es)} edges")

def config_infomap_multi_level(wiki: WikiNetwork, trials=5):
    '''
    使用Infomap階層算法對wiki.G進行社群檢測
    '''

    args = f"--directed --num-trials {trials}"
    im = infomap.Infomap(args=args)

    # 取得所有邊的 (source, target) 節點索引列表
    edge_list = wiki.G.get_edgelist()

    # 取得所有邊的權重列表
    weights = wiki.G.es["weight"]

    # 合併成 (source, target, weight) 的列表
    edges_info = [(src, tgt, w) for (src, tgt), w in zip(edge_list, weights)]
    
    im.add_links(edges_info)
    
    im.run()
    # 取得每個節點的多階層社群路徑
    node_path_map = {}
    node_flow = {}
    for node in im.nodes:
        if node.is_leaf:
            node_id = node.node_id  # 這就是 igraph 的 index
            node_path_map[node_id] = node.path
            node_flow[node_id] = node.flow

    # 依照 igraph 節點順序建立 paths
    community_paths = [node_path_map.get(v.index, []) for v in wiki.G.vs]
    wiki.G.vs['community_path'] = community_paths
    wiki.G.vs['flow'] = [node_flow.get(v.index, 0) for v in wiki.G.vs]
    for level in range(1,4):
        wiki.G.vs[f'community_level_{level}'] = [
            path[level-1] if len(path) > level-1 else None for path in community_paths
        ]

    wiki.im = im
    wiki.codelength_multi_level = im.codelength
    # config multi-level subgraphs
    config_G_list_multi_level_subgraphs(wiki)

def config_G_list_multi_level_subgraphs(wiki: WikiNetwork):
    '''
    創建多階層子圖
    wiki.G_list_multi_level_1_subgraphs
    wiki.G_list_multi_level_2_subgraphs
    wiki.G_list_multi_level_3_subgraphs
    '''
    if 'community_path' not in wiki.G.vs.attributes():
        raise ValueError("community_path not in G.vs.attributes()")
    for level in range(1,4):
        if f'community_level_{level}' not in wiki.G.vs.attributes():
            raise ValueError(f"community_level_{level} not in G.vs.attributes()")
    dict_level_1_nodes = {}  # key: community_level_1, value: set(node_id)
    for v in wiki.G.vs:
        if f'community_level_1' in v.attributes():
            community_level_1 = v[f'community_level_1']
            if community_level_1 is not None:
                dict_level_1_nodes.setdefault(community_level_1, set()).add(v.index)
    dict_level_2_nodes = {}  # key: community_level_2, value: set(node_id)
    for v in wiki.G.vs:
        if f'community_level_2' in v.attributes():
            community_level_2 = v[f'community_level_2']
            if community_level_2 is not None:
                dict_level_2_nodes.setdefault(community_level_2, set()).add(v.index)
    dict_level_3_nodes = {}  # key: community_level_3, value: set(node_id)
    for v in wiki.G.vs:
        if f'community_level_3' in v.attributes():
            community_level_3 = v[f'community_level_3']
            if community_level_3 is not None:
                dict_level_3_nodes.setdefault(community_level_3, set()).add(v.index)
    
    for key, value in dict_level_1_nodes.items():
        subgraph = wiki.G.subgraph(value)

    
        

class graph_utils:
    def __init__(self):
        pass
    
    # 確保igraph的屬性符合規範
    def justify_igraph_properties(G):
        '''
        input:
            G: igraph.Graph object
        return:
            dict{
                'graph': igraph.Graph object,
                'flag_modified': bool
            }
        vertex properties:
            idx: int (should not be float) 
            title: str
            tag: json string -> set()              #hub, authority, bridge, ...
            community: int (should not be float)
            community_path: json string -> tuple(int)
            flow: float 
            betweenness: float 
            community_level_1~3: int (should not be float)
        es properties:
            source_idx: int (should not be float) 
            target_idx: int (should not be float) 
            weight: float 
            betweenness: float 
            connections_num: int (should not be float)
            distance: float 
        '''
        if G is None:
            raise ValueError("G is None")
        if not isinstance(G, ig.Graph):
            raise ValueError("G is not a igraph.Graph object")
        # 有無修改過的flag
        flag_modified = False
        G = G.copy()
        # 確保vertex的attributes符合規範
        vertex_attrs = G.vs.attributes()
        vertex_int_attrs = set(['idx', 'community', 'community_level_1', 'community_level_2', 'community_level_3'])
        vertex_float_attrs = set(['flow', 'betweenness'])
        vertex_legal_attrs = vertex_int_attrs | vertex_float_attrs | set(['tag', 'community_path', 'title'])
        for attr in vertex_attrs:
            if attr not in vertex_legal_attrs:
                del G.vs[attr]
                continue
            if attr in vertex_int_attrs:
                for v in G.vs:
                    if v[attr] is not None:
                        try:
                            v[attr] = int(v[attr])
                            flag_modified = True
                        except:
                            print(f"{v.index}: {attr} type error, which is {type(v[attr])}: {v[attr]}")
                            v[attr] = None
            elif attr == 'community_path':
                for v in G.vs:
                    if v[attr] is not None:
                        try:
                            v[attr] = tuple(int(i) for i in v[attr])
                            flag_modified = True
                        except:
                            print(f"{v.index}: {attr} type error, which is {type(v[attr])}")
                            v[attr] = None        
        # 確保edge的attributes符合規範
        edge_attrs = G.es.attributes()
        edge_int_attrs = set(['source_idx', 'target_idx', 'connections_num'])
        edge_float_attrs = set(['weight','betweenness','distance'])
        edge_legal_attrs = edge_int_attrs | edge_float_attrs
        for attr in edge_attrs:
            if attr not in edge_legal_attrs:
                del G.es[attr]
                continue
            if attr in edge_int_attrs:
                for e in G.es:
                    if e[attr] is not None:
                        try:
                            e[attr] = int(e[attr])
                            flag_modified = True
                        except:
                            print(f"{e.source}->{e.target}: {attr} type error, which is {type(e[attr])}")
                            e[attr] = None
        return {'graph': G, 'flag_modified': flag_modified}
    
    def read_graphML(filename, justify_properties=True):
        '''
        input:
            filename: str
            justify_properties: bool
        return:
            dict{
                'graph': igraph.Graph object,
                'flag_modified': bool
            }
        vertex properties:
            idx: int (should not be float)
            title: str
            tag: json string -> set()
            community: int (should not be float)
            community_path: json string -> tuple(int)
            flow: float
            community_level_1~n: int (should not be float)
        es properties:
            weight: float (to vertex normalization)
        '''
        if filename is None:
            raise ValueError("filename is None")
        if not os.path.exists(filename):
            print(f"file {filename} not found")
            return {'graph': None, 'flag_modified': False}
        if not filename.endswith('.graphml'):
            raise ValueError(f"filename {filename} is not a graphml file")
        G = ig.read(filename)
        if justify_properties:
            result = graph_utils.justify_igraph_properties(G)
            return result
        else:
            return {'graph': G, 'flag_modified': False}

    def write_graphML(G, filename, justify_properties=True):
        '''
        保存圖形數據:
        vertex attributes:
            idx: int (should not be float)
            title: str
            tag: json string -> set()
            community: int (should not be float)
            community_path: json string -> tuple(int)
            flow: float
            community_level_1: int (should not be float)
            community_level_2: int (should not be float)
            community_level_3: int (should not be float)
        es attributes:
            weight: float (to vertex normalization)
        
        return: flag_modified
            True: 修改過
            False: 沒有修改過
        '''
        if G is None:
            print(f"G is None")
            return None
        if not isinstance(G, ig.Graph):
            raise ValueError("G is not a igraph.Graph object")
        G = G.copy()
        flag_modified = False
        if justify_properties:
            result = graph_utils.justify_igraph_properties(G)
            G = result['graph']
            flag_modified = result['flag_modified']
        G.write_graphml(filename)
        return flag_modified

    def write_json(G, filename,justify_properties=True):
        '''
        輸入:
            G: igraph.Graph object
            filename: str
        輸出:
            True: 有修改過
            False: 沒有修改過
        '''
        if G is None:
            print(f"G is None")
            return False
        tmp = isinstance(G, ig.Graph)
        if not tmp:
            print(f"G is not a igraph.Graph object")
            return False
        if justify_properties:
            result = graph_utils.justify_igraph_properties(G)
            G = result['graph']
            flag_modified = result['flag_modified']
        else:
            flag_modified = False
        # 創建nodes和edges
        nodes = []
        edges = []
        for v in G.vs:
            node = {}
            # 確保可以儲存成 json 格式
            for attr in G.vs.attributes():
                if attr == 'tag' or attr == 'community_path':
                    if v[attr] is not None:
                        try:
                            node[attr] = list(v[attr]) 
                        except:
                            print(f"{v.index}: {attr} type error, which is {type(v[attr])}: {v[attr]}")
                            node[attr] = []
                    else:
                        node[attr] = []
                else:
                    node[attr] = v[attr]
            nodes.append(node)
        for e in G.es:
            edge = {}
            for attr in G.es.attributes():
                edge[attr] = e[attr]
            edges.append(edge)
        # 儲存到json file
        with open(filename, 'w', encoding='utf-8') as f:   
            json.dump({
                'nodes': nodes,
                'edges': edges
            }, f, ensure_ascii=False, indent=2)
        return flag_modified

    def get_vertex_out_edges_weight_title(G, vertex_idx):
        """
        獲取節點的鄰居的邊權重和title
        參數:
            G (igraph.Graph): igraph有向圖
            vertex_idx (int): 節點的索引
        返回:
            plt.hist(weights, bins=100)
            (weights, titles)
        """
        edges = G.es.select(_source=vertex_idx)
        info = []
        for edge in edges:
            info.append({
                'weight': edge['weight'],
                'title': G.vs[edge.target]['title']
            })
        # Sort info list by weight in descending order
        info.sort(key=lambda x: x['weight'], reverse=True)
        print(f"source: {G.vs[vertex_idx]['title']}")
        print(f'info:[(weight,title)]')
        # print some basic statistics
        weights = [i["weight"] for i in info]
        print(f'average weight: {np.mean(weights)}')
        print(f'std weight: {np.std(weights)}')
        plt.hist(weights, bins=100)
        print('weights_histogram:')
        plt.show()
        return info

    def get_similarity_topology(G, vertex1, vertex2):
        """
        比較有向圖G中，兩個節點的出邊連結到的節點
        
        參數:
            G (igraph.Graph): igraph有向圖 
            index1 (int): 第一個節點的索引
            index2 (int): 第二個節點的索引
        返回:
            similarity_topology (float): len(common) / len(neighbors2)  
        """
        try:        
            if vertex1 is None or vertex2 is None:
                raise ValueError(f"節點不在圖中")
                
            # 獲取兩個節點的出邊目標節點
            neighbors1 = set(G.neighbors(vertex1))
            neighbors2 = set(G.neighbors(vertex2))
            
            # 計算共同連結和獨有連結
            common = neighbors1.intersection(neighbors2)
            
            # 計算相似度
            if len(common)==0:
                similarity = 0.0001
            else:
                similarity = len(common) / (len(neighbors2)) if len(neighbors1) > 0 and len(neighbors2) > 0 else 0.0001

            return similarity
            
        except Exception as e:
            print(f"比較過程中發生錯誤: {str(e)}")
            traceback.print_exc()
            return None


