import { getApiBaseUrl } from '../config';
import {
  AnalysisDecomposition,
  AnalysisReport,
  AnalysisStep,
  AnalysisSummary,
  HealthState,
  StreamEventData,
} from '../types/chatbi';

export interface StreamCallbacks {
  onSqlChunk: (chunk: string) => void;
  onSqlDone: (sql: string, durationMs: number) => void;
  onResult: (data: StreamEventData, totalDurationMs: number) => void;
  onError: (error: string, errorType?: string) => void;
}

/** 通用 SSE 解析：把响应体逐块解析为 (事件名, 数据) */
async function consumeSse(
  response: Response,
  onEvent: (eventType: string, data: any) => void
): Promise<void> {
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
      let eventData: any = {};

      for (const line of trimmed.split('\n')) {
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

      if (eventType) {
        onEvent(eventType, eventData);
      }
    }
  }
}

/** 把非 2xx 响应转换为可读错误消息 */
async function readErrorMessage(response: Response): Promise<string> {
  const errText = await response.text();
  let parsedMsg = `HTTP 错误 ${response.status}`;
  try {
    const json = JSON.parse(errText);
    parsedMsg = json.error || json.detail || parsedMsg;
  } catch {
    if (errText) parsedMsg = errText;
  }
  return parsedMsg;
}

export async function executeStreamQuery(
  question: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const apiBase = getApiBaseUrl();
  const startTime = performance.now();
  const sqlStartTime = startTime;
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
      callbacks.onError(await readErrorMessage(response), 'http_error');
      return;
    }

    await consumeSse(response, (eventType, eventData: StreamEventData) => {
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
    });
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw err;
    }
    callbacks.onError(err.message || '网络请求异常', 'network');
  }
}

/* ==================== 归因分析流式接口 ==================== */

export interface AnalyzeStreamCallbacks {
  onStart?: (data: { question: string }) => void;
  onDecompositionStart?: () => void;
  onDecompositionDone?: (data: AnalysisDecomposition) => void;
  onPlanReady?: (data: { total_steps: number; analysis_goal?: string; question_type?: string }) => void;
  onStepStart?: (data: AnalysisStep) => void;
  onStepSqlChunk?: (data: { step_id: string; content: string }) => void;
  onStepSqlDone?: (data: { step_id: string; sql: string }) => void;
  onStepResult?: (data: {
    step_id: string;
    columns: string[];
    rows: Record<string, any>[];
    row_count: number;
  }) => void;
  onStepDone?: (data: AnalysisStep) => void;
  onStepRetry?: (data: {
    step_id: string;
    attempt: number;
    max_attempts?: number;
    mode: 'rewrite' | 'retry';
    previous_sql?: string;
    previous_error?: string;
  }) => void;
  onStepError?: (data: { step_id: string; error: string; error_type?: string }) => void;
  onSummaryDone?: (data: AnalysisSummary) => void;
  onReportStart?: () => void;
  onReportDone?: (data: AnalysisReport) => void;
  onError?: (error: string, errorType?: string) => void;
  onDone?: (data: { completed_steps: number; failed_steps: number; skipped_steps: number }) => void;
}

export async function executeAnalyzeStream(
  question: string,
  callbacks: AnalyzeStreamCallbacks,
  options?: { maxSteps?: number; signal?: AbortSignal }
): Promise<void> {
  const apiBase = getApiBaseUrl();

  try {
    const response = await fetch(`${apiBase}/api/v1/analyze/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question,
        ...(options?.maxSteps ? { max_steps: options.maxSteps } : {}),
      }),
      signal: options?.signal,
    });

    if (!response.ok) {
      callbacks.onError?.(await readErrorMessage(response), 'http_error');
      return;
    }

    await consumeSse(response, (eventType, data) => {
      switch (eventType) {
        case 'start':
          callbacks.onStart?.(data);
          break;
        case 'decomposition_start':
          callbacks.onDecompositionStart?.();
          break;
        case 'decomposition_done':
          callbacks.onDecompositionDone?.(data);
          break;
        case 'plan_ready':
          callbacks.onPlanReady?.(data);
          break;
        case 'step_start':
          callbacks.onStepStart?.(data);
          break;
        case 'step_sql_chunk':
          callbacks.onStepSqlChunk?.(data);
          break;
        case 'step_sql_done':
          callbacks.onStepSqlDone?.(data);
          break;
        case 'step_result':
          callbacks.onStepResult?.(data);
          break;
        case 'step_done':
          callbacks.onStepDone?.(data);
          break;
        case 'step_retry':
          callbacks.onStepRetry?.(data);
          break;
        case 'step_error':
          callbacks.onStepError?.(data);
          break;
        case 'summary_done':
          callbacks.onSummaryDone?.(data);
          break;
        case 'report_start':
          callbacks.onReportStart?.();
          break;
        case 'report_done':
          callbacks.onReportDone?.(data);
          break;
        case 'error':
          callbacks.onError?.(data.error || '归因分析出错', data.error_type || 'analysis');
          break;
        case 'done':
          callbacks.onDone?.(data);
          break;
        default:
          console.log('未知归因事件类型:', eventType, data);
      }
    });
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw err;
    }
    callbacks.onError?.(err.message || '网络请求异常', 'network');
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
