import React, { useState } from 'react';
import { Button, Tooltip, Tag, message } from 'antd';
import {
  CopyOutlined,
  CheckOutlined,
  CodeOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';

interface SqlViewerProps {
  sql: string;
  isStreaming?: boolean;
  durationMs?: number;
}

// 轻量级 SQL 语法高亮解析器
function renderHighlightedSql(sql: string) {
  if (!sql) return null;

  // 匹配关键字、函数、字符串、数字、注释
  const tokens = sql.split(/(\s+|--[^\n]*|\/\*[\s\S]*?\*\/|'[^']*'|"(?:[^"\\]|\\.)*"|[(),;=<>!+\-*/%])/g);

  const keywords = new Set([
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN',
    'GROUP', 'BY', 'HAVING', 'ORDER', 'ASC', 'DESC', 'LIMIT', 'OFFSET',
    'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS', 'ON',
    'UNION', 'ALL', 'DISTINCT', 'AS', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE', 'CREATE', 'TABLE',
    'DROP', 'ALTER', 'VIEW', 'INDEX', 'WITH', 'INTERVAL', 'DATE', 'NULL', 'IS'
  ]);

  const functions = new Set([
    'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'ROUND', 'COALESCE', 'CONCAT',
    'SUBSTRING', 'DATE_FORMAT', 'DATE_SUB', 'NOW', 'STRFTIME', 'CAST',
    'DATEADD', 'DATEDIFF', 'LOWER', 'UPPER', 'TRIM', 'LENGTH', 'IFNULL'
  ]);

  return tokens.map((token, index) => {
    if (!token) return null;

    const upper = token.toUpperCase();

    if (keywords.has(upper)) {
      return (
        <span key={index} className="sql-token-keyword">
          {token}
        </span>
      );
    }

    if (functions.has(upper)) {
      return (
        <span key={index} className="sql-token-function">
          {token}
        </span>
      );
    }

    if (token.startsWith("'") || token.startsWith('"')) {
      return (
        <span key={index} className="sql-token-string">
          {token}
        </span>
      );
    }

    if (token.startsWith('--') || token.startsWith('/*')) {
      return (
        <span key={index} className="sql-token-comment">
          {token}
        </span>
      );
    }

    if (/^-?\d+(\.\d+)?$/.test(token)) {
      return (
        <span key={index} className="sql-token-number">
          {token}
        </span>
      );
    }

    return <span key={index}>{token}</span>;
  });
}

export const SqlViewer: React.FC<SqlViewerProps> = ({
  sql,
  isStreaming = false,
  durationMs,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!sql) return;
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      message.success('SQL 已复制到剪贴板');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      message.error('复制失败，请手动复制');
    }
  };

  const formatDuration = (ms?: number) => {
    if (!ms) return null;
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  return (
    <div className="sql-viewer-card">
      <div className="sql-viewer-header">
        <div className="sql-header-title">
          <CodeOutlined style={{ color: '#89b4fa', marginRight: 6 }} />
          <span>生成的 SQL 查询语句</span>
        </div>

        <div className="sql-header-actions">
          {durationMs !== undefined && (
            <Tag
              icon={<ClockCircleOutlined />}
              color="blue"
              style={{ borderRadius: 4, marginRight: 8, fontSize: 12 }}
            >
              生成耗时 {formatDuration(durationMs)}
            </Tag>
          )}

          <Tooltip title={copied ? '已复制' : '复制 SQL'}>
            <Button
              type="text"
              size="small"
              icon={copied ? <CheckOutlined style={{ color: '#52c41a' }} /> : <CopyOutlined />}
              onClick={handleCopy}
              className="sql-action-btn"
            >
              {copied ? '已复制' : '复制'}
            </Button>
          </Tooltip>
        </div>
      </div>

      <div className="sql-code-container">
        <pre className="sql-code-content">
          <code>
            {renderHighlightedSql(sql || '')}
            {isStreaming && <span className="sql-streaming-cursor" />}
          </code>
        </pre>
      </div>
    </div>
  );
};
