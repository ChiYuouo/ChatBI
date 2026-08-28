import React, { useState } from 'react';
import {
  Table,
  Empty,
  Alert,
  Typography,
  Button,
  Tag,
  Space,
  Segmented,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  TableOutlined,
  FileTextOutlined,
  DownloadOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

interface ResultViewProps {
  columns?: string[];
  rows?: Record<string, any>[];
  rowCount?: number;
  formatted?: string;
  totalDurationMs?: number;
  error?: string;
  errorType?: string;
  status: string;
}

const ERROR_TYPE_MAP: Record<string, { label: string; color: string }> = {
  validation: { label: '输入校验失败', color: 'orange' },
  request_validation: { label: '参数校验失败', color: 'orange' },
  llm: { label: 'LLM 生成失败', color: 'volcano' },
  security: { label: '安全规则拦截', color: 'red' },
  database_sql_syntax: { label: 'SQL 语法错误', color: 'magenta' },
  database_connection_error: { label: '数据库连接异常', color: 'red' },
  database_query_timeout: { label: '查询执行超时', color: 'gold' },
  database: { label: '数据库执行错误', color: 'red' },
  network: { label: '网络通信异常', color: 'red' },
  http_error: { label: 'HTTP 异常', color: 'volcano' },
};

export const ResultView: React.FC<ResultViewProps> = ({
  columns = [],
  rows = [],
  rowCount,
  formatted,
  totalDurationMs,
  error,
  errorType,
  status,
}) => {
  const [viewMode, setViewMode] = useState<'table' | 'text'>('table');

  // 导出 CSV 功能
  const handleExportCsv = () => {
    if (!columns.length || !rows.length) return;

    const escapeCsv = (val: any) => {
      if (val === null || val === undefined) return '';
      const str = String(val);
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const header = columns.map(escapeCsv).join(',');
    const body = rows
      .map((row) => columns.map((col) => escapeCsv(row[col])).join(','))
      .join('\n');

    const csvContent = '\uFEFF' + header + '\n' + body;
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `query_result_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  // 1. 错误状态
  if (error) {
    const errorInfo = (errorType && ERROR_TYPE_MAP[errorType]) || {
      label: '查询执行失败',
      color: 'red',
    };

    return (
      <div className="result-view-container">
        <Alert
          message={
            <Space>
              <Tag color={errorInfo.color} style={{ fontWeight: 600 }}>
                {errorInfo.label}
              </Tag>
              <Text strong>执行未完成</Text>
            </Space>
          }
          description={
            <div style={{ marginTop: 8 }}>
              <Paragraph
                type="danger"
                style={{
                  fontFamily: 'monospace',
                  background: '#fff1f0',
                  padding: '8px 12px',
                  borderRadius: 6,
                  border: '1px solid #ffa39e',
                  marginBottom: 0,
                  whiteSpace: 'pre-wrap',
                }}
              >
                {error}
              </Paragraph>
            </div>
          }
          type="error"
          showIcon
          icon={<WarningOutlined />}
          style={{ borderRadius: 8 }}
        />
      </div>
    );
  }

  // 2. 正在执行状态（还没拿到 result 数据前）
  if (status === 'generating_sql' || status === 'executing_query') {
    return null;
  }

  // 3. 空结果状态
  if (status === 'success' && (!rows || rows.length === 0)) {
    return (
      <div className="result-view-container">
        <div className="result-empty-box">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div>
                <Text strong style={{ color: '#595959' }}>
                  查询成功，但未找到匹配的数据
                </Text>
                <div style={{ color: '#8c8c8c', fontSize: 13, marginTop: 4 }}>
                  数据源中当前没有符合查询条件的数据记录。
                </div>
              </div>
            }
          />
        </div>
      </div>
    );
  }

  // 4. 成功结果数据表格构建
  const tableColumns: ColumnsType<Record<string, any>> = columns.map((colKey) => {
    // 智能检测该列是否为纯数值或日期类型以提供排序
    const sampleVal = rows[0]?.[colKey];
    const isNumber = typeof sampleVal === 'number' || (!isNaN(Number(sampleVal)) && sampleVal !== '' && sampleVal !== null);

    return {
      title: colKey,
      dataIndex: colKey,
      key: colKey,
      ellipsis: true,
      sorter: (a, b) => {
        const valA = a[colKey];
        const valB = b[colKey];
        if (isNumber) {
          return Number(valA || 0) - Number(valB || 0);
        }
        return String(valA || '').localeCompare(String(valB || ''));
      },
      render: (val) => {
        if (val === null || val === undefined) {
          return <Text type="secondary" italic>NULL</Text>;
        }
        if (typeof val === 'boolean') {
          return val ? <Tag color="green">true</Tag> : <Tag color="default">false</Tag>;
        }
        return String(val);
      },
    };
  });

  const displayCount = rowCount !== undefined ? rowCount : rows.length;

  return (
    <div className="result-view-container">
      <div className="result-header">
        <div className="result-title-group">
          <Text strong style={{ fontSize: 15 }}>
            查询结果数据集
          </Text>
          <Tag color="cyan" icon={<CheckCircleOutlined />} style={{ marginLeft: 8 }}>
            共 {displayCount} 行数据
          </Tag>
          {totalDurationMs !== undefined && (
            <Tag icon={<ClockCircleOutlined />} color="default">
              总耗时 {totalDurationMs < 1000 ? `${totalDurationMs}ms` : `${(totalDurationMs / 1000).toFixed(2)}s`}
            </Tag>
          )}
        </div>

        <Space size="small">
          {formatted && (
            <Segmented
              size="small"
              value={viewMode}
              onChange={(val) => setViewMode(val as 'table' | 'text')}
              options={[
                { label: '表格视图', value: 'table', icon: <TableOutlined /> },
                { label: '格式化视图', value: 'text', icon: <FileTextOutlined /> },
              ]}
            />
          )}

          <Tooltip title="导出当前表格数据为 CSV 文件">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={handleExportCsv}
            >
              导出 CSV
            </Button>
          </Tooltip>
        </Space>
      </div>

      {viewMode === 'table' ? (
        <div className="result-table-wrapper">
          <Table
            dataSource={rows.map((r, i) => ({ ...r, _key: i }))}
            rowKey="_key"
            columns={tableColumns}
            size="middle"
            bordered
            scroll={{ x: 'max-content', y: 420 }}
            pagination={
              rows.length > 10
                ? {
                    pageSize: 10,
                    showSizeChanger: true,
                    pageSizeOptions: ['10', '20', '50', '100'],
                    showTotal: (total) => `共 ${total} 条数据`,
                    size: 'small',
                  }
                : false
            }
          />
        </div>
      ) : (
        <div className="result-formatted-wrapper">
          <pre className="result-formatted-text">{formatted}</pre>
        </div>
      )}
    </div>
  );
};
