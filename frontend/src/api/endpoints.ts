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
export const collectTrendKeywords = (categories: number[], opts?: { translate?: boolean; fill_total_products?: boolean }) =>
  api.post('/keywords/trend', { categories, translate: opts?.translate ?? true, fill_total_products: opts?.fill_total_products ?? true });
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

// Insights
export const getNewKeywords = (days_back: number = 1, category?: string) =>
  api.get('/insights/new', { params: { days_back, category } });
export const getKeywordChanges = (days_back: number = 1, category?: string, classification?: string) =>
  api.get('/insights/changes', { params: { days_back, category, classification } });
export const getKeywordTimeseries = (keyword_jp: string, days: number = 30) =>
  api.get('/insights/timeseries', { params: { keyword_jp, days } });
