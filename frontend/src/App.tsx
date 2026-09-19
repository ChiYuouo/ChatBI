import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ConfigProvider, App as AntdApp, theme, message } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { XProvider } from '@ant-design/x';
import { Header } from './components/Header';
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
import { executeAnalyzeStream, executeStreamQuery, fetchHealth } from './services/chatbiApi';
import './App.css';

/** 归因链路中处于运行态的状态集合 */
const RUNNING_ANALYSIS_STATUS = new Set([
  'decomposing',
  'planning',
  'executing',
  'summarizing',
  'reporting',
]);

export const MainContent: React.FC = () => {
  const [inputQuestion, setInputQuestion] = useState('');
  const [mode, setMode] = useState<QueryMode>('query');
  const [loading, setLoading] = useState(false);
  const [feed, setFeed] = useState<FeedItem[]>([]);
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

          onError: (errMsg, errorType) =>
            patchAnalysis(analysisId, (r) => ({
              ...r,
              status: 'error',
              error: errMsg,
              errorType: errorType || 'analysis',
              totalDurationMs: Math.round(performance.now() - startedAt),
            })),
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

  // 8. 清空所有记录
  const handleClearAll = () => {
    setFeed([]);
    message.success('已清空所有记录');
  };

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
        onClearHistory={handleClearAll}
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
          <MainContent />
        </AntdApp>
      </XProvider>
    </ConfigProvider>
  );
}
