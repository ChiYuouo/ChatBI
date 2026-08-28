import React, { useState } from 'react';
import { Card, Button, Tooltip, Space, Typography, Tag } from 'antd';
import {
  QuestionCircleFilled,
  DeleteOutlined,
  RedoOutlined,
  DownOutlined,
  UpOutlined,
  BranchesOutlined,
} from '@ant-design/icons';
import { QueryRecord } from '../types/chatbi';
import { SqlViewer } from './SqlViewer';
import { ResultView } from './ResultView';
import { QueryStatusChain } from './QueryStatusChain';

const { Text } = Typography;

interface QueryCardProps {
  record: QueryRecord;
  onRetry: (question: string) => void;
  onDelete: (id: string) => void;
  isLatestRunning?: boolean;
}

export const QueryCard: React.FC<QueryCardProps> = ({
  record,
  onRetry,
  onDelete,
  isLatestRunning,
}) => {
  // 默认展开思维链（如果在运行中），完成后可折叠以聚焦在 SQL 与数据结果上
  const [showThoughtChain, setShowThoughtChain] = useState(isLatestRunning);

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const isStreaming = record.status === 'generating_sql';
  const isExecuting = record.status === 'executing_query';

  return (
    <Card
      className="query-card-item"
      bordered={false}
      style={{
        marginBottom: 20,
        borderRadius: 12,
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.05)',
      }}
    >
      {/* 1. 用户提问 Header */}
      <div className="query-question-row">
        <div className="question-content">
          <div className="q-badge">Q</div>
          <Text strong style={{ fontSize: 16, color: '#1f1f1f' }}>
            {record.question}
          </Text>
        </div>

        <div className="question-actions">
          <Text type="secondary" style={{ fontSize: 12, marginRight: 12 }}>
            {formatTime(record.createdAt)}
          </Text>

          <Space size={4}>
            <Tooltip title="查看/折叠执行流程">
              <Button
                type="text"
                size="small"
                icon={<BranchesOutlined />}
                onClick={() => setShowThoughtChain((prev) => !prev)}
                style={{ color: showThoughtChain ? '#1677ff' : '#8c8c8c' }}
              >
                {showThoughtChain ? <UpOutlined /> : <DownOutlined />}
              </Button>
            </Tooltip>

            <Tooltip title="以此问题重新查询">
              <Button
                type="text"
                size="small"
                icon={<RedoOutlined />}
                onClick={() => onRetry(record.question)}
                style={{ color: '#8c8c8c' }}
              />
            </Tooltip>

            <Tooltip title="删除此记录">
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                onClick={() => onDelete(record.id)}
                style={{ color: '#8c8c8c' }}
              />
            </Tooltip>
          </Space>
        </div>
      </div>

      {/* 2. 执行阶段状态链 (运行中或用户点击查看时展示) */}
      {(showThoughtChain || isStreaming || isExecuting) && (
        <div style={{ marginTop: 12, marginBottom: 12 }}>
          <QueryStatusChain
            status={record.status}
            sqlDurationMs={record.sqlDurationMs}
            totalDurationMs={record.totalDurationMs}
            rowCount={record.rowCount}
            error={record.error}
          />
        </div>
      )}

      {/* 3. 生成的 SQL 突出展示区 */}
      {(record.sql || isStreaming) && (
        <div style={{ marginTop: 14 }}>
          <SqlViewer
            sql={record.sql}
            isStreaming={isStreaming}
            durationMs={record.sqlDurationMs}
          />
        </div>
      )}

      {/* 4. 查询结果数据展示区 */}
      <div style={{ marginTop: 14 }}>
        <ResultView
          columns={record.columns}
          rows={record.rows}
          rowCount={record.rowCount}
          formatted={record.formatted}
          totalDurationMs={record.totalDurationMs}
          error={record.error}
          errorType={record.errorType}
          status={record.status}
        />
      </div>
    </Card>
  );
};
