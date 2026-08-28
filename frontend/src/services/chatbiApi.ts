import { getApiBaseUrl } from '../config';
import { HealthState, StreamEventData } from '../types/chatbi';

export interface StreamCallbacks {
  onSqlChunk: (chunk: string) => void;
  onSqlDone: (sql: string, durationMs: number) => void;
  onResult: (data: StreamEventData, totalDurationMs: number) => void;
  onError: (error: string, errorType?: string) => void;
}

export async function executeStreamQuery(
  question: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const apiBase = getApiBaseUrl();
  const startTime = performance.now();
  let sqlStartTime = startTime;
  let fullSql = '';

  try {
    const response = await fetch(`${apiBase}/api/v1/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question }),
      signal,
    });

    if (!response.ok) {
      const errText = await response.text();
      let parsedMsg = `HTTP 错误 ${response.status}`;
      try {
        const json = JSON.parse(errText);
        parsedMsg = json.error || json.detail || parsedMsg;
      } catch {
        if (errText) parsedMsg = errText;
      }
      callbacks.onError(parsedMsg, 'http_error');
      return;
    }

    if (!response.body) {
      throw new Error('未收到响应数据流');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;

        let eventType = '';
        let eventData: StreamEventData = {};

        const lines = trimmed.split('\n');
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            try {
              eventData = JSON.parse(line.slice(6));
            } catch (e) {
              console.warn('解析 SSE data 失败:', line, e);
            }
          }
        }

        if (!eventType) continue;

        switch (eventType) {
          case 'sql_chunk': {
            if (eventData.content) {
              fullSql += eventData.content;
              callbacks.onSqlChunk(eventData.content);
            }
            break;
          }
          case 'sql_done': {
            const finalSql = eventData.sql || fullSql;
            const sqlDuration = performance.now() - sqlStartTime;
            callbacks.onSqlDone(finalSql, Math.round(sqlDuration));
            break;
          }
          case 'result': {
            const totalDuration = performance.now() - startTime;
            callbacks.onResult(eventData, Math.round(totalDuration));
            break;
          }
          case 'error': {
            callbacks.onError(
              eventData.error || '执行出错',
              eventData.error_type || 'database'
            );
            break;
          }
          default:
            console.log('未知 SSE 事件类型:', eventType, eventData);
        }
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw err;
    }
    callbacks.onError(err.message || '网络请求异常', 'network');
  }
}

export async function fetchHealth(): Promise<HealthState> {
  const apiBase = getApiBaseUrl();
  try {
    const res = await fetch(`${apiBase}/health`, { signal: AbortSignal.timeout(4000) });
    if (!res.ok) {
      return {
        status: 'error',
        databaseConnected: false,
        message: `HTTP ${res.status}`,
      };
    }
    const data = await res.json();
    return {
      status: data.status === 'ok' ? 'ok' : 'error',
      databaseConnected: !!data.database_connected,
    };
  } catch (err: any) {
    return {
      status: 'error',
      databaseConnected: false,
      message: err.message || '无法连接后端服务',
    };
  }
}
