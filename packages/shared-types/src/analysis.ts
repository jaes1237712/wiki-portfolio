/**
 * 異常偵測與線性回歸的型別。
 * 數值行為必須與舊版 `web_wiki/src/lib/server/python_api/analysis.py` 一致:
 * z-score 是對 log10(pageviews + 1) 計算,門檻 > 1.96 視為異常。
 */
import type { IsoDate, PageviewPoint } from './pageviews.js';

export const ANOMALY_ZSCORE_THRESHOLD = 1.96;

export interface AnomalyPoint extends PageviewPoint {
  zScore: number;
}

/** 單一節點在指定日期區間內的異常偵測結果。 */
export interface AnomalyResult {
  idx: number;
  anomalies: AnomalyPoint[];
  normal: PageviewPoint[];
}

/** 預先算好的異常表(pipeline 批次產出),支援分頁/排序。 */
export interface AnomalyTableRow {
  idx: number;
  title: string;
  anomalyDate: IsoDate;
  pageviews: number;
  zScore: number;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface RegressionFit {
  /** 每日斜率。 */
  coef: number | null;
  intercept: number | null;
  r2Score: number | null;
}

/** 多個節點加總後的趨勢線,外加每個節點各自的回歸係數。 */
export interface RegressionResult {
  startDate: IsoDate;
  endDate: IsoDate;
  sum: RegressionFit & {
    originalData: PageviewPoint[];
    trendLine: PageviewPoint[];
  };
  perNode: Record<number, RegressionFit>;
}
