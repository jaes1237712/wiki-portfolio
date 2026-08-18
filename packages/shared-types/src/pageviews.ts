/** 瀏覽量時間序列型別。日期一律用 `YYYY-MM-DD` 字串,避免時區問題。 */

export type IsoDate = string;

export interface PageviewPoint {
  date: IsoDate;
  pageviews: number;
}

/** 日資料或半月彙總資料;`granularity` 標明是哪一種。 */
export interface PageviewSeries {
  idx: number;
  granularity: PageviewGranularity;
  points: PageviewPoint[];
}

export type PageviewGranularity = 'daily' | 'half-month';

/** 整個社群的瀏覽量加總序列。 */
export interface CommunityPageviewSeries {
  community: number;
  points: PageviewPoint[];
}
