import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ConfigProvider, App as AntdApp, theme, message } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { XProvider } from '@ant-design/x';
import { Header } from './components/Header';
import { LoginPage } from './components/LoginPage';
import { SessionSidebar } from './components/SessionSidebar';
import { QueryInputBar } from './components/QueryInputBar';
import { QueryCard } from './components/QueryCard';
import { AnalysisCard } from './components/AnalysisCard';
import { EmptyState } from './components/EmptyState';
import {
  AnalysisRecord,
  AnalysisStep,
  FeedItem,
  HealthState,
  QueryMode,
  QueryRecord,
} from './types/chatbi';
import {
  clearSessionHistory,
  clearToken,
  executeAnalyzeStream,
  executeStreamQuery,
  fetchHealth,
  fetchSessionTurns,
  parseReportMarkdown,
  getToken,
  listSessions,
  peekSessionId,
  resetSessionId,
  setActiveSessionId,
  SessionSummary,
} from './services/chatbiApi';
import './App.css';

/** 归因链路中处于运行态的状态集合 */
const RUNNING_ANALYSIS_STATUS = new Set([
  'decomposing',
  'planning',
  'executing',
  'summarizing',
  'reporting',
]);

/** 单跳查询中处于运行态的状态集合 */
const RUNNING_QUERY_STATUS = new Set(['generating_sql', 'executing_query']);

/* ==================== 对话记录的本地持久化 ==================== */

const FEED_STORAGE_KEY = 'chatbi_feed';

/**
 * 只保留最近 N 条。
 * sessionStorage 上限约 5MB，而单条记录可能含大量结果行，
 * 必须截断，否则写满配额会导致后续写入静默失败。
 */
const MAX_PERSISTED_ITEMS = 20;

/** 刷新后运行中的记录已无法续跑，恢复时统一标记为中断 */
function reviveFeedItem(raw: any): FeedItem | null {
  if (!raw || !raw.record) return null;

  const record = { ...raw.record, createdAt: new Date(raw.record.createdAt) };

  if (raw.kind === 'query') {
    if (RUNNING_QUERY_STATUS.has(record.status)) {
      record.status = 'cancelled';
      record.error = '页面刷新导致查询中断';
      record.errorType = 'interrupted';
    }
    return { kind: 'query', record };
  }

  if (raw.kind === 'analysis') {
    if (RUNNING_ANALYSIS_STATUS.has(record.status)) {
      record.status = 'cancelled';
      record.error = '页面刷新导致分析中断';
      record.errorType = 'interrupted';
    }
    // 步骤级的 running 不处理会一直转圈，恢复时退化为「已跳过」
    record.steps = (record.steps || []).map((step: any) =>
      step.status === 'running' ? { ...step, status: 'skipped' } : step
    );
    return { kind: 'analysis', record };
  }

  return null;
}

function loadPersistedFeed(): FeedItem[] {
  try {
    const raw = sessionStorage.getItem(FEED_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(reviveFeedItem)
      .filter((item): item is FeedItem => item !== null);
  } catch {
    return [];
  }
}

/** 丢掉结果行，只保留结构与 SQL（配额不足时的降级形态） */
function stripRows(item: FeedItem): FeedItem {
  if (item.kind === 'query') {
    return { kind: 'query', record: { ...item.record, rows: undefined } };
  }
  return {
    kind: 'analysis',
    record: {
      ...item.record,
      steps: item.record.steps.map((step) => ({ ...step, rows: undefined })),
    },
  };
}

/** 写入 sessionStorage；超配额时降级重试，最终失败也不影响正常使用 */
function persistFeed(feed: FeedItem[]): void {
  const recent = feed.slice(0, MAX_PERSISTED_ITEMS);
  try {
    sessionStorage.setItem(FEED_STORAGE_KEY, JSON.stringify(recent));
    return;
  } catch {
    // 配额不足，走下面的降级路径
  }
  try {
    sessionStorage.setItem(FEED_STORAGE_KEY, JSON.stringify(recent.map(stripRows)));
  } catch {
    console.warn('对话记录持久化失败（存储配额不足），本次会话不再保存历史');
  }
}

/** 清空本地保存的对话记录 */
export function clearPersistedFeed(): void {
  try {
    sessionStorage.removeItem(FEED_STORAGE_KEY);
  } catch {
    /* storage 不可用时无需处理 */
  }
}

interface MainContentProps {
  /** token 失效（后端 401）后回到登录页 */
  onUnauthorized: () => void;
  /** 退出登录 */
  onLogout: () => void;
}

export const MainContent: React.FC<MainContentProps> = ({ onUnauthorized, onLogout }) => {
  const [inputQuestion, setInputQuestion] = useState('');
  const [mode, setMode] = useState<QueryMode>('query');
  const [loading, setLoading] = useState(false);
  const [feed, setFeed] = useState<FeedItem[]>(loadPersistedFeed);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionIdState] = useState<string | null>(() =>
    peekSessionId()
  );
  const [health, setHealth] = useState<HealthState>({
    status: 'checking',
    databaseConnected: false,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  // 1. 初始化检查健康状态
  const loadHealth = useCallback(async () => {
    const res = await fetchHealth();
    setHealth(res);
  }, []);

  useEffect(() => {
    loadHealth();
    const interval = setInterval(loadHealth, 30000); // 30秒巡检一次
    return () => clearInterval(interval);
  }, [loadHealth]);

  // 对话记录持久化：刷新后仍能看到历史。
  // debounce 300ms —— 流式过程中 setFeed 会被高频调用，不能每次都写 storage。
  useEffect(() => {
    const timer = setTimeout(() => persistFeed(feed), 300);
    return () => clearTimeout(timer);
  }, [feed]);

  // 拉取当前登录用户的会话列表（侧边栏数据源）
  const loadSessions = useCallback(async () => {
    setSessions(await listSessions());
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  /** 更新指定归因记录 */
  const patchAnalysis = useCallback(
    (id: string, updater: (record: AnalysisRecord) => AnalysisRecord) => {
      setFeed((prev) =>
        prev.map((item) =>
          item.kind === 'analysis' && item.record.id === id
            ? { kind: 'analysis', record: updater(item.record) }
            : item
        )
      );
    },
    []
  );

  /** 更新归因记录中的某个步骤 */
  const patchStep = useCallback(
    (id: string, stepId: string, updater: (step: AnalysisStep) => AnalysisStep) => {
      patchAnalysis(id, (record) => ({
        ...record,
        steps: record.steps.map((step) => (step.step_id === stepId ? updater(step) : step)),
      }));
    },
    [patchAnalysis]
  );

  // 2. 发起单跳查询（自然语言 -> SQL -> 执行 -> 结果表格）
  const handleQuery = async (question: string) => {
    const queryId = `query_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const newRecord: QueryRecord = {
      id: queryId,
      question: question.trim(),
      sql: '',
      status: 'generating_sql',
      createdAt: new Date(),
    };

    setFeed((prev) => [{ kind: 'query', record: newRecord }, ...prev]);
    setInputQuestion('');
    setLoading(true);

    const abortCtrl = new AbortController();
    abortControllerRef.current = abortCtrl;

    try {
      await executeStreamQuery(
        question.trim(),
        {
          onRewriteDone: (_originalQuestion, rewrittenQuestion) => {
            setFeed((prev) =>
              prev.map((item) =>
                item.kind === 'query' && item.record.id === queryId
                  ? {
                      kind: 'query',
                      record: { ...item.record, rewrittenQuestion },
                    }
                  : item
              )
            );
          },
          onSqlChunk: (chunk) => {
            setFeed((prev) =>
              prev.map((item) =>
                item.kind === 'query' && item.record.id === queryId
                  ? {
                      kind: 'query',
                      record: {
                        ...item.record,
                        sql: (item.record.sql || '') + chunk,
                        status: 'generating_sql',
                      },
                    }
                  : item
              )
            );
          },
          onSqlDone: (finalSql, durationMs) => {
            setFeed((prev) =>
              prev.map((item) =>
                item.kind === 'query' && item.record.id === queryId
                  ? {
                      kind: 'query',
                      record: {
                        ...item.record,
                        sql: finalSql,
                        sqlDurationMs: durationMs,
                        status: 'executing_query',
                      },
                    }
                  : item
              )
            );
          },
          onResult: (data, totalDurationMs) => {
            // 新一轮已落库 —— 刷新侧边栏的会话顺序与轮数
            void loadSessions();
            setFeed((prev) =>
              prev.map((item) =>
                item.kind === 'query' && item.record.id === queryId
                  ? {
                      kind: 'query',
                      record: {
                        ...item.record,
                        columns: data.columns || [],
                        rows: data.rows || [],
                        rowCount: data.row_count ?? (data.rows ? data.rows.length : 0),
                        formatted: data.formatted,
                        totalDurationMs,
                        status: 'success',
                      },
                    }
                  : item
              )
            );
          },
          onError: (errMsg, errorType) => {
            // 401 时 authedFetch 已清 token —— 据此回到登录页
            if (!getToken()) {
              onUnauthorized();
              return;
            }
            setFeed((prev) =>
              prev.map((item) =>
                item.kind === 'query' && item.record.id === queryId
                  ? {
                      kind: 'query',
                      record: {
                        ...item.record,
                        error: errMsg,
                        errorType: errorType || 'database',
                        status: 'error',
                      },
                    }
                  : item
              )
            );
          },
        },
        abortCtrl.signal
      );
    } catch (err: any) {
      if (err.name === 'AbortError') {
        message.info('已取消查询请求');
        setFeed((prev) =>
          prev.map((item) =>
            item.kind === 'query' && item.record.id === queryId
              ? {
                  kind: 'query',
                  record: {
                    ...item.record,
                    error: '用户主动取消查询',
                    errorType: 'cancelled',
                    status: 'cancelled',
                  },
                }
              : item
          )
        );
      } else {
        message.error(err.message || '查询异常中断');
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  // 3. 发起归因分析（拆解 -> 多步执行 -> 汇总 -> 报告）
  const handleAnalyze = async (question: string) => {
    const analysisId = `analysis_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const startedAt = performance.now();

    const newRecord: AnalysisRecord = {
      id: analysisId,
      question: question.trim(),
      status: 'decomposing',
      steps: [],
      createdAt: new Date(),
    };

    setFeed((prev) => [{ kind: 'analysis', record: newRecord }, ...prev]);
    setInputQuestion('');
    setLoading(true);

    const abortCtrl = new AbortController();
    abortControllerRef.current = abortCtrl;

    try {
      await executeAnalyzeStream(
        question.trim(),
        {
          onStart: () => patchAnalysis(analysisId, (r) => ({ ...r, status: 'decomposing' })),

          onDecompositionStart: () =>
            patchAnalysis(analysisId, (r) => ({ ...r, status: 'decomposing' })),

          onDecompositionDone: (data) =>
            patchAnalysis(analysisId, (r) => ({
              ...r,
              status: 'planning',
              decomposition: data,
              analysisGoal: data?.analysis_goal,
              questionType: data?.question_type,
            })),

          onPlanReady: (data) =>
            patchAnalysis(analysisId, (r) => ({
              ...r,
              status: 'executing',
              totalSteps: data?.total_steps,
              analysisGoal: data?.analysis_goal ?? r.analysisGoal,
              questionType: data?.question_type ?? r.questionType,
            })),

          onStepStart: (data) =>
            patchAnalysis(analysisId, (r) => {
              const exists = r.steps.some((step) => step.step_id === data.step_id);
              const steps = exists
                ? r.steps.map((step) =>
                    step.step_id === data.step_id
                      ? { ...step, ...data, status: 'running' as const }
                      : step
                  )
                : [...r.steps, { ...data, status: 'running' as const }];

              return {
                ...r,
                status: 'executing',
                steps,
                totalSteps: data.total_steps ?? r.totalSteps,
              };
            }),

          onStepSqlChunk: ({ step_id, content }) =>
            patchStep(analysisId, step_id, (step) => ({
              ...step,
              sqlStream: (step.sqlStream || '') + content,
            })),

          onStepSqlDone: ({ step_id, sql }) =>
            patchStep(analysisId, step_id, (step) => ({ ...step, sql })),

          onStepResult: ({ step_id, columns, rows, row_count }) =>
            patchStep(analysisId, step_id, (step) => ({
              ...step,
              columns,
              rows,
              rowCount: row_count,
            })),

          onStepDone: (data) =>
            patchAnalysis(analysisId, (r) => ({
              ...r,
              steps: r.steps.map((step) =>
                step.step_id === data.step_id
                  ? {
                      ...step,
                      ...data,
                      // 保留运行期累积的 SQL 流式内容，避免被空值覆盖
                      sql: data.sql || step.sql || step.sqlStream,
                      sqlStream: undefined,
                      errorType: (data as any).error_type ?? step.errorType,
                      repaired: (data as any).repaired ?? step.repaired,
                    }
                  : step
              ),
            })),

          onStepRetry: ({ step_id, attempt, max_attempts, mode, previous_sql, previous_error }) =>
            patchStep(analysisId, step_id, (step) => ({
              ...step,
              // 重写期间给个明确状态，避免用户以为卡住
              status: 'running',
              error: undefined,
              retries: [
                ...(step.retries || []),
                {
                  attempt,
                  maxAttempts: max_attempts,
                  mode,
                  previousSql: previous_sql,
                  previousError: previous_error,
                },
              ],
            })),

          onStepError: ({ step_id, error }) =>
            patchStep(analysisId, step_id, (step) => ({
              ...step,
              status: 'failed',
              error,
            })),

          onSummaryDone: (data) =>
            patchAnalysis(analysisId, (r) => ({ ...r, status: 'summarizing', summary: data })),

          onReportStart: () => patchAnalysis(analysisId, (r) => ({ ...r, status: 'reporting' })),

          onReportDone: (data) =>
            patchAnalysis(analysisId, (r) => ({ ...r, status: 'success', report: data })),

          onDone: () =>
            patchAnalysis(analysisId, (r) => ({
              ...r,
              status: 'success',
              totalDurationMs: Math.round(performance.now() - startedAt),
            })),

          onError: (errMsg, errorType) => {
            if (!getToken()) {
              onUnauthorized();
              return;
            }
            patchAnalysis(analysisId, (r) => ({
              ...r,
              status: 'error',
              error: errMsg,
              errorType: errorType || 'analysis',
              totalDurationMs: Math.round(performance.now() - startedAt),
            }));
          },
        },
        { signal: abortCtrl.signal }
      );
    } catch (err: any) {
      if (err.name === 'AbortError') {
        message.info('已取消归因分析');
        patchAnalysis(analysisId, (r) => ({
          ...r,
          status: 'cancelled',
          error: '用户主动取消分析',
        }));
      } else {
        message.error(err.message || '归因分析异常中断');
        patchAnalysis(analysisId, (r) => ({
          ...r,
          status: 'error',
          error: err.message || '归因分析异常中断',
        }));
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  // 4. 提交入口：按当前模式分流
  const handleSubmit = (question: string) => {
    if (!question.trim() || loading) return;
    if (mode === 'analyze') {
      handleAnalyze(question);
    } else {
      handleQuery(question);
    }
  };

  // 5. 取消当前请求
  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  // 6. 重试：沿用记录自身的类型，避免混用两种链路
  const handleRetryQuery = (question: string) => {
    setInputQuestion(question);
    handleQuery(question);
  };

  const handleRetryAnalysis = (question: string) => {
    setInputQuestion(question);
    handleAnalyze(question);
  };

  // 7. 删除记录
  const handleDeleteRecord = (id: string) => {
    setFeed((prev) => prev.filter((item) => item.record.id !== id));
    message.success('已删除记录');
  };

  // 8. 开启新会话
  // 合并了原「清空记录」：只清展示、不重置会话会留下一个隐患 ——
  // 用户以为记录清了，后端其实还在用那些历史做上下文。
  const handleNewSession = () => {
    // 「新会话」只是离开当前对话 —— 会话原样保留在侧边栏里，
    // 删除走列表项的删除按钮（带二次确认）。多会话并存是它的语义前提。
    resetSessionId();
    clearPersistedFeed();
    setFeed([]);
    setInputQuestion('');
    setActiveSessionIdState(null);
    message.success('已开启新会话');
  };

  /** 从侧边栏切换到某个历史会话：回填记录并切换上下文 */
  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      if (sessionId === peekSessionId()) return;
      // 有查询正在跑就先取消 —— 否则结果会写进已切走的会话界面
      if (loading && abortControllerRef.current) {
        abortControllerRef.current.abort();
        setLoading(false);
      }
      const turns = await fetchSessionTurns(sessionId);
      setActiveSessionId(sessionId);
      setActiveSessionIdState(sessionId);
      // 接口按时间正序返回，feed 渲染最新在前 → 反转。
      // 带回答文本的是归因轮次：还原成归因卡片渲染报告；普通查询照旧走查询卡片。
      const items: FeedItem[] = [...turns]
        .reverse()
        .map((turn, index): FeedItem => {
          const base = {
            id: `history_${sessionId.slice(0, 8)}_${index}`,
            question: turn.question,
            createdAt: new Date(turn.created_at || Date.now()),
          };
          if (turn.answer) {
            return {
              kind: 'analysis',
              record: {
                ...base,
                status: 'success' as const,
                // 历史记录没有步骤明细，空数组让过程区收起、只展示报告
                steps: [],
                report: parseReportMarkdown(turn.answer),
              },
            };
          }
          return {
            kind: 'query',
            record: {
              ...base,
              sql: turn.sql || '',
              status: 'success' as const,
            },
          };
        });
      setFeed(items);
      setInputQuestion('');
    },
    [loading]
  );

  /** 删除某个历史会话；删的是当前会话时自动切到全新会话 */
  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      await clearSessionHistory(sessionId);
      await loadSessions();
      if (sessionId === peekSessionId()) {
        // 删的是当前会话：切到全新会话，避免界面还挂着已删记录
        resetSessionId();
        clearPersistedFeed();
        setFeed([]);
        setActiveSessionIdState(null);
        message.success('已删除当前会话');
      } else {
        message.success('已删除会话');
      }
    },
    [loadSessions]
  );

  const isLatestRunning = (item: FeedItem, index: number) => {
    if (index !== 0 || !loading) return false;
    if (item.kind === 'query') {
      return item.record.status === 'generating_sql' || item.record.status === 'executing_query';
    }
    return RUNNING_ANALYSIS_STATUS.has(item.record.status);
  };

  return (
    <div className="chatbi-app-layout">
      <Header
        health={health}
        onRefreshHealth={loadHealth}
        historyCount={feed.length}
        onLogout={onLogout}
      />

      <div className="chatbi-body">
        <SessionSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelect={handleSelectSession}
          onDelete={handleDeleteSession}
          onNewSession={handleNewSession}
        />
        <main className="chatbi-main-container">
        <QueryInputBar
          value={inputQuestion}
          onChange={setInputQuestion}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
          loading={loading}
          disabled={false}
          mode={mode}
          onModeChange={setMode}
        />

        <div className="chatbi-feed-section">
          {feed.length === 0 ? (
            <EmptyState />
          ) : (
            feed.map((item, index) =>
              item.kind === 'query' ? (
                <QueryCard
                  key={item.record.id}
                  record={item.record}
                  onRetry={handleRetryQuery}
                  onDelete={handleDeleteRecord}
                  isLatestRunning={isLatestRunning(item, index)}
                />
              ) : (
                <AnalysisCard
                  key={item.record.id}
                  record={item.record}
                  onRetry={handleRetryAnalysis}
                  onDelete={handleDeleteRecord}
                  isLatestRunning={isLatestRunning(item, index)}
                />
              )
            )
          )}
        </div>
      </main>
      </div>
    </div>
  );
};

/** 登录门控：未登录只显示登录页，登录后进入工作台 */
const AuthGate: React.FC = () => {
  const [authed, setAuthed] = useState(() => !!getToken());

  if (!authed) {
    return <LoginPage onLogin={() => setAuthed(true)} />;
  }

  return (
    <MainContent
      onUnauthorized={() => setAuthed(false)}
      onLogout={() => {
        // 退出同时清掉会话标识与对话记录，换账号后从新开始
        clearToken();
        clearPersistedFeed();
        setAuthed(false);
      }}
    />
  );
};

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 8,
          fontFamily: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`,
        },
      }}
    >
      <XProvider>
        <AntdApp>
          <AuthGate />
        </AntdApp>
      </XProvider>
    </ConfigProvider>
  );
}
