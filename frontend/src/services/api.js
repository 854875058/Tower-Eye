/**
 * API 服务层
 * 封装所有后端 API 调用
 */
import axios from 'axios';

// 创建 axios 实例
const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || 'http://10.132.19.82:8001',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 可以在这里添加 token 等认证信息
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data;
  },
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// ============================================================================
// API 接口定义
// ============================================================================

/**
 * 健康检查
 */
export const healthCheck = () => {
  return api.get('/api/health');
};

/**
 * 多维度检索
 */
export const search = (params) => {
  return api.post('/api/search', params);
};

/**
 * 获取统计概览
 */
export const getStatisticsOverview = (params) => {
  return api.get('/api/statistics/overview', { params });
};

/**
 * 获取地图统计数据
 */
export const getMapStatistics = (params) => {
  return api.get('/api/statistics/map', { params });
};

/**
 * 获取事件详情
 */
export const getEventDetail = (eventId) => {
  return api.get(`/api/events/${eventId}`);
};

/**
 * 获取媒体文件 URL
 */
export const getMediaUrl = (assetId) => {
  return `http://localhost:8000/api/media/${assetId}`;
};

/**
 * 获取配置信息
 */
export const getConfig = () => {
  return api.get('/api/config');
};

export default api;
