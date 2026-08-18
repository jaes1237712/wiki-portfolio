import pandas as pd
from statsmodels.tsa.seasonal import seasonal_decompose
from sklearn.ensemble import IsolationForest
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from functools import reduce

# 以色列 3511
# 中華民國憲法 151954
# 金融危機 13260

# def get_test_data(idx, startDate='2025-04-01', endDate='2025-04-30'):
#     '''
#     startDate: 2024-01-01
#     endDate: 2024-12-31
#     '''
#     url = f"http://localhost:4173/api/pageviews/{idx}?start={startDate}&end={endDate}"  
#     resp = requests.get(url)
#     return resp.json()

# test_datas = [get_test_data(3511), get_test_data(151954), get_test_data(13260)]

def merge_datas_to_dataframe(datas):
    '''
        datas: [data1, data2, data3, ...]
        data1: [
            {'date': 2024-01-01, 'pageviews': 1000},
            {'date': 2024-01-02, 'pageviews': 2000},
            ...
        ]
        return: dataframe(date, sumPageviews, pageviews1, pageviews2, pageviews3, ...)
    '''
    # 先將每個 data 轉為 dataframe 並設置 index（date）
    dfs = []
    for i, data in enumerate(datas, 1):
        df = pd.DataFrame(data).set_index('date')
        df = df.rename(columns={'pageviews': f'pageviews{i}'})
        dfs.append(df)

    # 用 reduce 和 pd.concat 快速橫向合併（對齊 index）
    df_merged = reduce(lambda left, right: pd.concat([left, right], axis=1), dfs)

    # 補齊缺失值為 0
    df_merged = df_merged.fillna(0)

    # 計算 sum_pageviews
    pageview_cols = [col for col in df_merged.columns if col.startswith('pageviews')]
    df_merged['sumPageviews'] = df_merged[pageview_cols].sum(axis=1)

    # 將欄位順序調整
    columns = ['sumPageviews'] + pageview_cols
    df_merged = df_merged[columns]

    # 重置 index，把 date 變回欄位，並排序
    df_merged = df_merged.reset_index().sort_values('date').reset_index(drop=True)

    return df_merged

def anomaly_detection(datas):
    '''
    Detect anomaly data by z-score, if z-score > 1.96, then is anomaly data
    input: datas = {
        'idx1':{'2024-01-01':1000, '2024-01-02':2000, ...},
        'idx2':{'2024-01-01':1000, '2024-01-02':2000, ...},
        ...
    }
    return {
      'idx1': {
            'anomaly': {
                'pageviews':{'2024-01-01':1000, '2024-01-02':2000, ...}
                'zScore':{'2024-01-01':2.0, '2024-01-02':3.0, ...}
            }, 
            'normal': 'pageviews':{'2024-01-01':1000, '2024-01-02':2000, ...}},
      ...
    }
    '''
    results = {}
    for idx, data in datas.items():
        # check if data is empty
        if not data:
            results[idx] = {
                'anomaly': {},
                'normal': {}
            }
            continue

        # Convert dictionary to DataFrame with date as index
        df = pd.Series(data).rename('pageviews').to_frame()
        df.index = pd.to_datetime(df.index)

        # 避免 pageviews 為 0 造成 log 問題，先加 1
        df['pageviews_log'] = np.log10(df['pageviews'] + 1)

        # Calculate z-score
        mean = df['pageviews_log'].mean()
        std = df['pageviews_log'].std()
        df['zScore'] = (df['pageviews_log'] - mean) / std

        anomaly_data_dict = {'pageviews': {}, 'zScore': {}}
        normal_data_dict = {'pageviews': {}}

        for date, row in df.iterrows():
            # Convert date back to string format 'YYYY-MM-DD' for the output dictionary key
            date_str = date.strftime('%Y-%m-%d')
            pageviews_int = int(row['pageviews'])
            if row['zScore'] > 1.96:
                anomaly_data_dict['pageviews'][date_str] = pageviews_int
                anomaly_data_dict['zScore'][date_str] = round(row['zScore'], 4) # Round z-score for readability
            else:
                normal_data_dict['pageviews'][date_str] = pageviews_int

        results[idx] = {
            'anomaly': anomaly_data_dict,
            'normal': normal_data_dict
        }

    return results

def linear_regression(datas):
    '''
    input: datas = {
        'idx1':{'2024-01-01':1000, '2024-01-02':2000, ...},
        'idx2':{'2024-01-01':1000, '2024-01-02':2000, ...},
        ...
    }
    return: {
        'start_date': '2024-01-01',
        'end_date': '2024-12-31',
        'sumPageviews': {
            'coef': 1.0,
            'intercept': 0.0,
            'r2Score': 0.9,
            'originalData': {'2024-01-01': 1000, '2024-01-02': 2000, ...},
            'trendLine': {'2024-01-01': 1000, '2024-01-02': 2000, ...},
        },
        'idx1': {
            'coef': 1.0,
            'intercept': 0.0,
            'r2Score': 0.9
            }
        }
    '''
    ad_results = anomaly_detection(datas)
    normal_datas = {idx: ad_results[idx]['normal']['pageviews'] for idx in ad_results}

    # Combine all normal data into a single DataFrame for sum calculation
    dfs = []
    for idx, data in normal_datas.items():
        if data:
            df = pd.Series(data, name=idx).to_frame()
            df.index = pd.to_datetime(df.index)
            dfs.append(df)

    if not dfs:
        return {}

    # Merge dataframes and calculate sum
    df_merged = reduce(lambda left, right: pd.merge(left, right, left_index=True, right_index=True, how='outer'), dfs)
    df_merged = df_merged.fillna(0)
    df_merged['sumPageviews'] = df_merged.sum(axis=1)

    # Prepare data for linear regression
    df_merged['dateNum'] = (df_merged.index - df_merged.index.min()).days

    startDate = df_merged.index.min().strftime('%Y-%m-%d')
    endDate = df_merged.index.max().strftime('%Y-%m-%d')

    results = {'startDate': startDate, 'endDate': endDate}

    # Function to perform linear regression
    def perform_regression(df_data, col_name):
        valid = df_data[col_name].notna() & (df_data[col_name] != 0) # Exclude 0 pageviews for regression
        if valid.sum() < 2:
            return {'coef': np.nan, 'intercept': np.nan, 'r2Score': np.nan}
        X = df_data.loc[valid, ['dateNum']].values.reshape(-1, 1)
        y = df_data.loc[valid, col_name].values
        model = LinearRegression()
        model.fit(X, y)
        y_pred = model.predict(X)
        r2 = r2_score(y, y_pred)
        return {'coef': model.coef_[0], 'intercept': model.intercept_, 'r2Score': r2}

    # Perform regression for sum_pageviews
    sum_reg_results = perform_regression(df_merged, 'sumPageviews')

    # Calculate trend line for sum_pageviews (using all dates)
    if not np.isnan(sum_reg_results['coef']):
        X_all = df_merged[['dateNum']].values.reshape(-1, 1)
        y_trend = sum_reg_results['coef'] * X_all.flatten() + sum_reg_results['intercept']
        trend_line_data = dict(zip(df_merged.index.strftime('%Y-%m-%d'), y_trend.round(2)))
    else:
        trend_line_data = {}

    results['sumPageviews'] = {
        **sum_reg_results,
        'originalData': dict(zip(df_merged.index.strftime('%Y-%m-%d'), df_merged['sumPageviews'].astype(int))),
        'trendLine': trend_line_data
    }

    # Perform regression for individual idx
    for idx in normal_datas:
         if idx in df_merged.columns:
             results[idx] = perform_regression(df_merged, idx)
         else:
             results[idx] = {'coef': np.nan, 'intercept': np.nan, 'r2Score': np.nan}

    return results
