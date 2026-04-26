export interface Keyword {
  id: number;
  keyword_jp: string;
  keyword_kr?: string;
  lookup_date?: string;
  category?: string;
  classification?: string;
  rank?: number;
  index_key?: string;
  competition_intensity?: number;
  search_volume_weekly?: number;
  search_volume_daily?: number;
  total_products?: number;
  products_jp?: number;
  products_kr?: number;
  products_cn?: number;
  products_other?: number;
  volume_change_flag?: string;
  bid_count?: number;
  bid_price_1?: number;
  bid_price_2?: number;
  bid_price_3?: number;
  bid_price_4?: number;
  bid_price_5?: number;
  bid_price_6?: number;
  bid_price_7?: number;
  bid_price_8?: number;
  bid_price_9?: number;
  bid_price_10?: number;
}

export interface TaskInfo {
  task_id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  total: number;
  message?: string;
}

export interface Qoo10Product {
  id: number;
  search_keyword?: string;
  product_name?: string;
  price_jpy?: number;
  shipping_fee?: string;
  origin?: string;
  cover_image_url?: string;
  product_url?: string;
  lookup_date?: string;
}

export interface BidHistory {
  id: number;
  lookup_date?: string;
  keyword_jp?: string;
  bid_count?: number;
  search_volume_weekly?: number;
  search_volume_daily?: number;
  bid_price_1?: number;
  bid_price_2?: number;
  bid_price_3?: number;
  bid_price_4?: number;
  bid_price_5?: number;
}

export interface TrackingItem {
  id: number;
  product_id: string;
  keyword: string;
  product_name?: string;
  cover_image_url?: string;
}

export interface BestsellerItem {
  id: number;
  category?: string;
  rank?: number;
  product_name?: string;
  brand?: string;
  price_jpy?: number;
  cover_image_url?: string;
  product_url?: string;
  sales_volume?: number;
  lookup_date?: string;
}

export interface LoginStatus {
  logged_in: boolean;
  browser_active: boolean;
}
