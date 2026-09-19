import React, { useState } from 'react';
import { Card, Button, Tooltip, Space, Typography, Tag, Alert, Progress } from 'antd';
import {
  DeleteOutlined,
  RedoOutlined,
  DownOutlined,
  UpOutlined,
  BranchesOutlined,
  PartitionOutlined,
  ClockCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { AnalysisRecord } from '../types/chatbi';
import { AnalysisStageBar } from './AnalysisStageBar';
import { AnalysisStepList } from './AnalysisStepList';
import { AnalysisReportView } from './AnalysisReportView';

const { Text, Paragraph } = Typography;

interface AnalysisCardProps {
  record: AnalysisRecord;
  onRetry: (question: string) => void;
  onDelete: (id: string) => void;
  isLatestRunning?: boolean;
}

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  decomposing: { label: '拆解中', color: 'processing' },
  planning: { label: '编排中', color: 'processing' },
  executing: { label: '执行中', color: 'processing' },
  summarizing: { label: '汇总中', color: 'processing' },
  reporting: { label: '归因中', color: 'processing' },
  success: { label: '已完成', color: 'success' },
  error: { label: '已失败', color: 'error' },
  cancelled: { label: '已取消', color: 'default' },
};

export const AnalysisCard: React.FC<AnalysisCardProps> = ({
  record,
  onRetry,
  onDelete,
  isLatestRunning,
}) => {
  // 运行中默认展开过程，完成后默认收起以突出归因结论
  const [showProcess, setShowProcess] = useState(!!isLatestRunning);

  const isRunning =
    record.status === 'decomposing' ||
    record.status === 'planning' ||
    record.status === 'executing' ||
    record.status === 'summarizing' ||
    record.status === 'reporting';

  const formatTime = (date: Date) =>
    date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });

  const formatDuration = (ms?: number) => {
    if (!ms) return null;
    return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
  };

  const statusMeta = STATUS_LABEL[record.status] || { label: record.status, color: 'default' };
  const executedSteps = record.steps.filter(
    (step) => step.status === 'success' || step.status === 'failed'
  ).length;
  const percent =
    record.totalSteps && record.totalSteps > 0
      ? Math.round((executedSteps / record.totalSteps) * 100)
      : 0;

  const subtasks = record.decomposition?.subtasks || [];

  return (
    <Card
      className="query-card-item analysis-card-item"
      variant="borderless"
      style={{
        marginBottom: 20,
        borderRadius: 12,
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.05)',
      }}
    >
      {/* 1. 提问头部 */}
      <div className="query-question-row">
        <div className="question-content">
          <div className="q-badge analysis-badge">归因</div>
          <Text strong style={{ fontSize: 16, color: '#1f1f1f' }}>
            {record.question}
          </Text>
        </div>

        <div className="question-actions">
          <Tag color={statusMeta.color} style={{ marginRight: 8 }}>
            {statusMeta.label}
          </Tag>

          {formatDuration(record.totalDurationMs) && (
            <Tag icon={<ClockCircleOutlined />} style={{ marginRight: 8 }}>
              {formatDuration(record.totalDurationMs)}
            </Tag>
          )}

          <Text type="secondary" style={{ fontSize: 12, marginRight: 12 }}>
            {formatTime(record.createdAt)}
          </Text>

          <Space size={4}>
            <Tooltip title="查看/折叠分析过程">
              <Button
                type="text"
                size="small"
                icon={<BranchesOutlined />}
                onClick={() => setShowProcess((prev) => !prev)}
                style={{ color: showProcess ? '#1677ff' : '#8c8c8c' }}
              >
                {showProcess ? <UpOutlined /> : <DownOutlined />}
              </Button>
            </Tooltip>

            <Tooltip title="以此问题重新分析">
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

      {/* 2. 阶段进度 */}
      {isRunning && (
        <div className="analysis-progress-wrapper">
          <Progress
            percent={percent}
            size="small"
            status="active"
            strokeColor="#1677ff"
            format={() => `${executedSteps}/${record.totalSteps ?? '—'}`}
          />
        </div>
      )}

      {/* 3. 错误提示 */}
      {(record.status === 'error' || record.status === 'cancelled') && (
        <div style={{ marginTop: 14 }}>
          <Alert
            type={record.status === 'cancelled' ? 'warning' : 'error'}
            showIcon
            icon={<WarningOutlined />}
            title={record.status === 'cancelled' ? '分析已取消' : '归因分析未完成'}
            description={
              record.error ? (
                <Paragraph
                  style={{
                    fontFamily: 'monospace',
                    background: '#fff1f0',
                    padding: '8px 12px',
                    borderRadius: 6,
                    border: '1px solid #ffa39e',
                    marginBottom: 0,
                    fontSize: 12,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {record.error}
                </Paragraph>
              ) : undefined
            }
            style={{ borderRadius: 8 }}
          />
        </div>
      )}

      {/* 4. 分析过程：阶段链 + 拆解结果 + 执行计划 */}
      {showProcess && (
        <div className="analysis-process">
          <AnalysisStageBar
            status={record.status}
            totalSteps={record.totalSteps}
            executedSteps={executedSteps}
          />

          {(record.analysisGoal || subtasks.length > 0) && (
            <div className="analysis-decomposition">
              <div className="analysis-section-title">
                <PartitionOutlined style={{ color: '#722ed1', marginRight: 6 }} />
                <Text strong style={{ fontSize: 14 }}>
                  问题拆解
                </Text>
                {record.questionType && (
                  <Tag color="purple" style={{ marginLeft: 8 }}>
                    {record.questionType}
                  </Tag>
                )}
              </div>

              {record.analysisGoal && (
                <div className="analysis-goal">
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    分析目标
                  </Text>
                  <div style={{ fontSize: 13, marginTop: 2 }}>{record.analysisGoal}</div>
                </div>
              )}

              {subtasks.length > 0 && (
                <div className="analysis-subtask-list">
                  {subtasks.map((task, index) => (
                    <div className="analysis-subtask-item" key={task.task_id}>
                      <span className="analysis-subtask-index">{index + 1}</span>
                      <div className="analysis-subtask-body">
                        <div className="analysis-subtask-name">
                          <Text strong style={{ fontSize: 13 }}>
                            {task.task_name}
                          </Text>
                          {task.task_type && (
                            <Tag variant="filled" style={{ marginLeft: 6, fontSize: 11 }}>
                              {task.task_type}
                            </Tag>
                          )}
                        </div>
                        {task.description && (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {task.description}
                          </Text>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <AnalysisStepList
            steps={record.steps}
            defaultActiveKeys={
              record.steps.filter((s) => s.status === 'running').map((s) => s.step_id)
            }
          />
        </div>
      )}

      {/* 5. 归因报告 */}
      <div style={{ marginTop: 14 }}>
        <AnalysisReportView
          report={record.report}
          pending={
            !record.report &&
            (record.status === 'reporting' || record.status === 'success')
          }
        />
      </div>
    </Card>
  );
};
