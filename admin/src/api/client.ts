import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Types
export interface User {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  is_admin: boolean;
  created_at: string;
}

export interface Channel {
  id: number;
  username: string;
  title: string | null;
  last_post_id: number;
  is_active: boolean;
  created_at: string;
  last_checked_at: string | null;
  subscribers_count?: number;
}

export interface Subscription {
  id: number;
  user_id: number;
  channel_id: number;
  created_at: string;
  user?: User;
  channel?: Channel;
}

export interface Post {
  id: number;
  channel_id: number;
  post_id: number;
  content: string | null;
  summary: string | null;
  created_at: string;
  channel?: Channel;
}

export interface Stats {
  total_users: number;
  total_channels: number;
  total_subscriptions: number;
  total_posts: number;
}

// Userbot types
export type UserbotState =
  | 'not_started'
  | 'waiting_code'
  | 'waiting_password'
  | 'authorized'
  | 'error';

export interface UserbotStatus {
  configured: boolean;
  state: UserbotState;
  phone?: string;
  message: string;
}

export interface UserbotResponse {
  success: boolean;
  state?: UserbotState;
  message?: string;
  error?: string;
}

// API functions
export const getStats = () => api.get<Stats>('/api/stats');
export const getUsers = () => api.get<User[]>('/api/users');
export const getChannels = () => api.get<Channel[]>('/api/channels');
export const getSubscriptions = () => api.get<Subscription[]>('/api/subscriptions');
export const getPosts = (limit?: number) => api.get<Post[]>('/api/posts', { params: { limit } });

export const deleteUser = (id: number) => api.delete(`/api/users/${id}`);
export const deleteChannel = (id: number) => api.delete(`/api/channels/${id}`);
export const toggleChannel = (id: number, is_active: boolean) =>
  api.patch(`/api/channels/${id}`, { is_active });

// Userbot API
export const getUserbotStatus = () => api.get<UserbotStatus>('/api/userbot/status');
export const startUserbotAuth = (phone_number: string) =>
  api.post<UserbotResponse>('/api/userbot/start', { phone_number });
export const confirmUserbotCode = (code: string) =>
  api.post<UserbotResponse>('/api/userbot/code', { code });
export const confirmUserbotPassword = (password: string) =>
  api.post<UserbotResponse>('/api/userbot/password', { password });
export const logoutUserbot = () => api.post<UserbotResponse>('/api/userbot/logout');
export const joinUserbotChannel = (username: string) =>
  api.post<UserbotResponse>('/api/userbot/join', { username });

// AI Settings types
export interface AISettings {
  provider: 'gemini' | 'claude';
  gemini_model: string;
  claude_model: string;
}

export interface AIStatus {
  provider: string;
  model: string;
  status: 'ok' | 'rate_limited' | 'error';
  message?: string;
}

export interface GeminiModel {
  name: string;
  displayName: string;
  inputTokenLimit: number;
  outputTokenLimit: number;
}

export interface ModelsResponse {
  models: GeminiModel[];
  count: number;
}

// AI Settings API
export const getAISettings = () => api.get<AISettings>('/api/ai/settings');
export const updateAISettings = (settings: Partial<AISettings>) =>
  api.put<AISettings>('/api/ai/settings', settings);
export const getAIStatus = () => api.get<AIStatus>('/api/ai/status');
export const getAvailableModels = () => api.get<ModelsResponse>('/api/ai/models');
