import api from './client';
import type { Keyword, LoginStatus, TaskInfo, Qoo10Product, BidHistory, TrackingItem, BestsellerItem } from '../types';

// Auth
export const getLoginStatus = () => api.get<LoginStatus>('/auth/status');
export const startLogin = () => api.post('/auth/login');
export const confirmLogin = () => api.post('/auth/confirm');
export const logout = () => api.post('/auth/logout');
export const getCredentials = () => api.get<{ user_id: string; has_password: boolean }>('/auth/credentials');
export const saveCredentials = (user_id: string, password: string) => api.post('/auth/credentials', { user_id, password });
export const deleteCredentials = () => api.delete('/auth/credentials');

// Keywords
export const getKeywords = () => api.get<Keyword[]>('/keywords');
export const deleteKeyword = (id: number) => api.delete(`/keywords/${id}`);
export const listKeywordDates = () => api.get<{ lookup_date: string; count: number }[]>('/keywords/dates');
export const deleteKeywordsByDate = (lookup_date: string) => api.delete(`/keywords/by-date/${lookup_date}`);
export const collectTrendKeywords = (categories: number[], opts?: { translate?: boolean; fill_total_products?: boolean; collect_bids?: boolean }) =>
  api.post('/keywords/trend', {
    categories,
    translate: opts?.translate ?? true,
    fill_total_products: opts?.fill_total_products ?? true,
    collect_bids: opts?.collect_bids ?? false,
  });
export const collectRelatedKeywords = (keywords: string[]) => api.post('/keywords/related', { keywords });

// Competition
export const analyzeCompetition = (keywords: string[]) => api.post('/competition/analyze', { keywords });

// Bid
export const getBidHistory = (keyword?: string) => api.get<BidHistory[]>('/bid/history', { params: { keyword } });
export const collectBidResults = (keywords: string[]) => api.post('/bid/collect', { keywords });

// Products
export const getQoo10Products = (keyword?: string) => api.get<Qoo10Product[]>('/products/qoo10', { params: { keyword } });
export const searchQoo10Products = (keyword: string) => api.post('/products/qoo10', { keyword });
export const searchCoupangProducts = (keyword: string) => api.post('/products/coupang', { keyword });
export const searchNaverProducts = (keyword: string) => api.post('/products/naver', { keyword });

// Tracking
export const getTrackingItems = () => api.get<TrackingItem[]>('/tracking/items');
export const addTrackingItem = (item: { product_id: string; keyword: string }) => api.post('/tracking/items', item);
export const runTracking = () => api.post('/tracking/run');

// Bestsellers
export const getBestsellers = (category?: string) => api.get<BestsellerItem[]>('/bestsellers', { params: { category } });
export const collectBestsellers = (category: number) => api.post('/bestsellers/collect', { params: { category } });

// Tasks
export const getTasks = () => api.get<TaskInfo[]>('/tasks');
export const getTask = (taskId: string) => api.get<TaskInfo>(`/tasks/${taskId}`);
export const cancelTask = (taskId: string) => api.delete(`/tasks/${taskId}`);

// Utils
export const getExchangeRate = (currency: string = 'JPY') => api.get('/utils/exchange-rate', { params: { currency } });
export const translate = (text: string, source: string = 'ko', target: string = 'ja') =>
  api.post('/utils/translate', { text, source, target });

// Margin
export interface MarginInput {
  weight_g: number;
  purchase_price_krw: number;
  shipping_packaging_krw: number;
  sell_price_jpy: number;
  exchange_rate?: number;
  use_exact_rate?: boolean;
  shipping_mode?: 'auto' | 'free_kse' | 'paid_tracx';
}
export const calculateMargin = (input: MarginInput) => api.post('/margin/calculate', input);
export const analyzeCompositions = (input: MarginInput) => api.post('/margin/analyze-compositions', input);

// Recommendations
export const collectRecommendations = (keywords_jp: string[], opts?: { include_naver?: boolean; include_qoo10?: boolean }) =>
  api.post('/recommendations/collect', { keywords_jp, include_naver: opts?.include_naver ?? true, include_qoo10: opts?.include_qoo10 ?? true });
export const getRecommendationReport = (keywords_jp: string[], opts?: { default_weight_g?: number; default_packaging_krw?: number; min_margin_rate?: number }) =>
  api.post('/recommendations/report', { keywords_jp, ...opts });

export interface AutoSourcingParams {
  mode: 'auto' | 'interest';
  min_search_volume: number;
  min_kr_ratio: number;
  max_kr_ratio: number;
  min_competition: number;
  max_competition: number;
  brand_filter: 'all' | 'general' | 'brand';
  keywords_limit: number;
  products_per_keyword: number;
  categories?: string[];
  interest_keywords?: string[];
}
export const listKeywordCategories = () => api.get<{ category: string; count: number }[]>('/keywords/categories');
export const previewAutoSourcing = (params: AutoSourcingParams) =>
  api.post('/recommendations/auto-sheet/preview', params);
export const runAutoSourcing = (params: AutoSourcingParams) =>
  api.post('/recommendations/auto-sheet', params);
export const fetchQoo10ProductsByKeywords = (keywords_jp: string[], per_keyword_limit: number) =>
  api.post('/recommendations/qoo10-products-by-keywords', { keywords_jp, per_keyword_limit });

// Insights
export const getNewKeywords = (days_back: number = 1, category?: string) =>
  api.get('/insights/new', { params: { days_back, category } });
export const getKeywordChanges = (days_back: number = 1, category?: string, classification?: string) =>
  api.get('/insights/changes', { params: { days_back, category, classification } });
export const getKeywordTimeseries = (keyword_jp: string, days: number = 30) =>
  api.get('/insights/timeseries', { params: { keyword_jp, days } });
