declare global {
  interface Window {
    CHATBI_CONFIG?: {
      apiBaseUrl?: string;
    };
  }
}

export const getApiBaseUrl = (): string => {
  if (typeof window !== 'undefined' && window.CHATBI_CONFIG?.apiBaseUrl) {
    return window.CHATBI_CONFIG.apiBaseUrl.replace(/\/+$/, '');
  }
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL.replace(/\/+$/, '');
  }
  // 如果通过开发服务器运行且端口不是 8000，优先使用 http://localhost:8000
  return 'http://localhost:8000';
};
