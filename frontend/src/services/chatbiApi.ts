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
  /** 多轮追问被改写时触发，便于界面展示「我理解为」 */
  onRewriteDone?: (originalQuestion: string, rewrittenQuestion: string) => void;
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

/* ==================== 登录与 token ==================== */

const TOKEN_KEY = 'chatbi_token';

export interface LoginResult {
  token: string;
  user: { user_id: string; username: string; role: string; region: string | null };
}

/** 登录已过期（后端 401），token 已被清除，需要回到登录页 */
export class UnauthorizedError extends Error {
  constructor() {
    super('登录已过期，请重新登录');
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage 不可用时本页内仍可使用 */
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const apiBase = getApiBaseUrl();
  const response = await fetch(`${apiBase}/api/v1/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json();
}

/** 带登录态的 fetch：自动附 Authorization；401 时清 token 并抛 UnauthorizedError */
async function authedFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    clearToken();
    throw new UnauthorizedError();
  }
  return response;
}

/* ==================== 会话标识 ==================== */

const SESSION_STORAGE_KEY = 'chatbi_session_id';

function createSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * 取当前会话 ID，首次调用时生成并写入 sessionStorage。
 *
 * 用 sessionStorage 而非 localStorage：同一标签页刷新后仍能接上上下文，
 * 新开标签页则是一段新会话。
 * 隐私模式等 storage 不可用时退化为进程内临时 ID —— 刷新会丢上下文，
 * 但不影响查询本身。
 */
let fallbackSessionId = '';

export function getOrCreateSessionId(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) return existing;
    const created = createSessionId();
    sessionStorage.setItem(SESSION_STORAGE_KEY, created);
    return created;
  } catch {
    if (!fallbackSessionId) {
      fallbackSessionId = createSessionId();
    }
    return fallbackSessionId;
  }
}

/**
 * 清掉当前会话标识，下一次请求会开启一段新会话。
 *
 * 注意：只重置前端标识还不够 —— 后端的历史是按 session_id 存的，
 * 换了 ID 才会让后端的上下文也从头开始。
 */
export function resetSessionId(): void {
  try {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    /* storage 不可用时清掉内存兜底值即可 */
  }
  fallbackSessionId = '';
}

/** 读取当前会话标识；不存在时返回 null（不会创建新的） */
export function peekSessionId(): string | null {
  try {
    return sessionStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return fallbackSessionId || null;
  }
}

/**
 * 清空指定会话在服务端的历史记录，返回删除条数。
 *
 * 「新会话」时必须调用：只换 session_id 不删数据的话，
 * 旧查询记录（含 SQL）会一直留在磁盘上，用户以为清了其实还在。
 * 删除失败一律忽略 —— 不能因为它阻断本地的重置动作。
 */
export async function clearSessionHistory(sessionId: string): Promise<number> {
  const apiBase = getApiBaseUrl();
  try {
    const response = await authedFetch(
      `${apiBase}/api/v1/session/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' }
    );
    if (!response.ok) return 0;
    const data = await response.json();
    return typeof data.deleted === 'number' ? data.deleted : 0;
  } catch {
    return 0;
  }
}

/** 显式设置当前活跃会话（侧边栏切换时用） */
export function setActiveSessionId(id: string): void {
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, id);
  } catch {
    fallbackSessionId = id;
  }
}

/* ==================== 会话列表（侧边栏） ==================== */

export interface SessionSummary {
  session_id: string;
  title: string;
  turns: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface SessionTurn {
  question: string;
  sql: string | null;
  created_at: string | null;
}

/** 当前登录用户的全部会话，按最后活动倒序 */
export async function listSessions(): Promise<SessionSummary[]> {
  const apiBase = getApiBaseUrl();
  try {
    const response = await authedFetch(`${apiBase}/api/v1/sessions`);
    if (!response.ok) return [];
    const data = await response.json();
    return data.sessions || [];
  } catch {
    return [];
  }
}

/** 某会话的全部轮次（时间正序），用于切换会话时回填历史 */
export async function fetchSessionTurns(sessionId: string): Promise<SessionTurn[]> {
  const apiBase = getApiBaseUrl();
  try {
    const response = await authedFetch(
      `${apiBase}/api/v1/session/${encodeURIComponent(sessionId)}/turns`
    );
    if (!response.ok) return [];
    const data = await response.json();
    return data.turns || [];
  } catch {
    return [];
  }
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
    const response = await authedFetch(`${apiBase}/api/v1/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question, session_id: getOrCreateSessionId() }),
      signal,
    });

    if (!response.ok) {
      callbacks.onError(await readErrorMessage(response), 'http_error');
      return;
    }

    await consumeSse(response, (eventType, eventData: StreamEventData) => {
      switch (eventType) {
        case 'rewrite_done': {
          callbacks.onRewriteDone?.(
            eventData.original_question || question,
            eventData.rewritten_question || ''
          );
          break;
        }
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
    const response = await authedFetch(`${apiBase}/api/v1/analyze/stream`, {
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
