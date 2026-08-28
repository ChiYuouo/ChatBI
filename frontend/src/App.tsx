import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ConfigProvider, App as AntdApp, theme, message } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { XProvider } from '@ant-design/x';
import { Header } from './components/Header';
import { QueryInputBar } from './components/QueryInputBar';
import { QueryCard } from './components/QueryCard';
import { EmptyState } from './components/EmptyState';
import { HealthState, QueryRecord } from './types/chatbi';
import { executeStreamQuery, fetchHealth } from './services/chatbiApi';
import './App.css';

export const MainContent: React.FC = () => {
  const [inputQuestion, setInputQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<QueryRecord[]>([]);
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

  // 2. 发起查询（自然语言 -> SQL -> 执行 -> 结果表格）
  const handleQuery = async (question: string) => {
    if (!question.trim() || loading) return;

    const queryId = `query_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const newRecord: QueryRecord = {
      id: queryId,
      question: question.trim(),
      sql: '',
      status: 'generating_sql',
      createdAt: new Date(),
    };

    setRecords((prev) => [newRecord, ...prev]);
    setInputQuestion('');
    setLoading(true);

    const abortCtrl = new AbortController();
    abortControllerRef.current = abortCtrl;

    try {
      await executeStreamQuery(
        question.trim(),
        {
          onSqlChunk: (chunk) => {
            setRecords((prev) =>
              prev.map((rec) =>
                rec.id === queryId
                  ? { ...rec, sql: (rec.sql || '') + chunk, status: 'generating_sql' }
                  : rec
              )
            );
          },
          onSqlDone: (finalSql, durationMs) => {
            setRecords((prev) =>
              prev.map((rec) =>
                rec.id === queryId
                  ? {
                      ...rec,
                      sql: finalSql,
                      sqlDurationMs: durationMs,
                      status: 'executing_query',
                    }
                  : rec
              )
            );
          },
          onResult: (data, totalDurationMs) => {
            setRecords((prev) =>
              prev.map((rec) =>
                rec.id === queryId
                  ? {
                      ...rec,
                      columns: data.columns || [],
                      rows: data.rows || [],
                      rowCount: data.row_count ?? (data.rows ? data.rows.length : 0),
                      formatted: data.formatted,
                      totalDurationMs,
                      status: 'success',
                    }
                  : rec
              )
            );
          },
          onError: (errMsg, errorType) => {
            setRecords((prev) =>
              prev.map((rec) =>
                rec.id === queryId
                  ? {
                      ...rec,
                      error: errMsg,
                      errorType: errorType || 'database',
                      status: 'error',
                    }
                  : rec
              )
            );
          },
        },
        abortCtrl.signal
      );
    } catch (err: any) {
      if (err.name === 'AbortError') {
        message.info('已取消查询请求');
        setRecords((prev) =>
          prev.map((rec) =>
            rec.id === queryId
              ? {
                  ...rec,
                  error: '用户主动取消查询',
                  errorType: 'cancelled',
                  status: 'cancelled',
                }
              : rec
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

  // 3. 取消查询
  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  // 4. 重试查询
  const handleRetry = (question: string) => {
    setInputQuestion(question);
    handleQuery(question);
  };

  // 5. 删除记录
  const handleDeleteRecord = (id: string) => {
    setRecords((prev) => prev.filter((r) => r.id !== id));
    message.success('已删除记录');
  };

  // 6. 清空所有记录
  const handleClearAll = () => {
    setRecords([]);
    message.success('已清空所有查询记录');
  };

  return (
    <div className="chatbi-app-layout">
      {/* 顶部 Header */}
      <Header
        health={health}
        onRefreshHealth={loadHealth}
        historyCount={records.length}
        onClearHistory={handleClearAll}
      />

      {/* 主体工作台容器 */}
      <main className="chatbi-main-container">
        {/* 输入与快捷提示区 */}
        <QueryInputBar
          value={inputQuestion}
          onChange={setInputQuestion}
          onSubmit={handleQuery}
          onCancel={handleCancel}
          loading={loading}
          disabled={false}
        />

        {/* 历史卡片流或初始欢迎界面 */}
        <div className="chatbi-feed-section">
          {records.length === 0 ? (
            <EmptyState />
          ) : (
            records.map((record, index) => (
              <QueryCard
                key={record.id}
                record={record}
                onRetry={handleRetry}
                onDelete={handleDeleteRecord}
                isLatestRunning={index === 0 && loading}
              />
            ))
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
