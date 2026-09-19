import React, { useState } from 'react';
import { Tag, Typography, Table, Empty, Collapse, Spin } from 'antd';
import {
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
  MinusCircleOutlined,
  RightOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { AnalysisStep, AnalysisStepStatus } from '../types/chatbi';
import { SqlViewer } from './SqlViewer';

const { Text, Paragraph } = Typography;

interface AnalysisStepListProps {
  steps: AnalysisStep[];
  /** 运行中默认展开当前步骤，便于观察实时进展 */
  defaultActiveKeys?: string[];
}

const STATUS_META: Record<
  AnalysisStepStatus,
  { color: string; label: string }
> = {
  pending: { color: '#bfbfbf', label: '等待中' },
  running: { color: '#1677ff', label: '执行中' },
  success: { color: '#52c41a', label: '已完成' },
  failed: { color: '#ff4d4f', label: '已失败' },
  skipped: { color: '#8c8c8c', label: '已跳过' },
};

const renderStatusIcon = (status: AnalysisStepStatus, index: number) => {
  if (status === 'running') {
    return <LoadingOutlined style={{ color: STATUS_META.running.color, fontSize: 15 }} />;
  }
  if (status === 'success') {
    return <CheckCircleFilled style={{ color: STATUS_META.success.color, fontSize: 15 }} />;
  }
  if (status === 'failed') {
    return <CloseCircleFilled style={{ color: STATUS_META.failed.color, fontSize: 15 }} />;
  }
  if (status === 'skipped') {
    return <MinusCircleOutlined style={{ color: STATUS_META.skipped.color, fontSize: 15 }} />;
  }
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 18,
        height: 18,
        borderRadius: '50%',
        border: '1px solid #d9d9d9',
        fontSize: 11,
        color: '#8c8c8c',
        lineHeight: 1,
      }}
    >
      {index}
    </span>
  );
};

/** 步骤内的紧凑结果表：只做展示，导出交给外层 */
const StepResultTable: React.FC<{
  columns?: string[];
  rows?: Record<string, any>[];
}> = ({ columns = [], rows = [] }) => {
  if (!rows.length) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={<Text type="secondary" style={{ fontSize: 12 }}>该步骤没有返回数据</Text>}
        style={{ margin: '8px 0' }}
      />
    );
  }

  const tableColumns: ColumnsType<Record<string, any>> = columns.map((key) => ({
    title: key,
    dataIndex: key,
    key,
    ellipsis: true,
    render: (val) => {
      if (val === null || val === undefined) {
        return <Text type="secondary" italic>NULL</Text>;
      }
      return String(val);
    },
  }));

  return (
    <Table
      dataSource={rows.map((r, i) => ({ ...r, _key: i }))}
      rowKey="_key"
      columns={tableColumns}
      size="small"
      bordered
      scroll={{ x: 'max-content', y: 240 }}
      pagination={rows.length > 5 ? { pageSize: 5, size: 'small' } : false}
    />
  );
};

export const AnalysisStepList: React.FC<AnalysisStepListProps> = ({
  steps,
  defaultActiveKeys,
}) => {
  const [activeKeys, setActiveKeys] = useState<string[]>(defaultActiveKeys || []);

  if (!steps.length) {
    return null;
  }

  const items = steps.map((step, idx) => {
    const meta = STATUS_META[step.status] || STATUS_META.pending;
    const sql = step.sql || step.sqlStream || '';
    const hasDetail = Boolean(sql || step.rows?.length || step.error);

    const header = (
      <div className="analysis-step-header">
        <span className="analysis-step-icon">{renderStatusIcon(step.status, idx + 1)}</span>

        <div className="analysis-step-title-group">
          <div className="analysis-step-name-row">
            <Text strong style={{ fontSize: 14 }}>
              {step.step_name}
            </Text>
            {step.task_type && (
              <Tag color="blue" style={{ marginLeft: 8, fontSize: 11 }}>
                {step.task_type}
              </Tag>
            )}
            <Tag color={step.status === 'running' ? 'processing' : 'default'} style={{ fontSize: 11 }}>
              {meta.label}
            </Tag>
            {step.attempts !== undefined && step.attempts > 1 && (
              <Tag color="orange" style={{ fontSize: 11 }}>
                第 {step.attempts} 次尝试
              </Tag>
            )}
            {step.repaired && (
              <Tag color="gold" style={{ fontSize: 11 }}>
                已按报错重写 SQL
              </Tag>
            )}
          </div>

          {step.description && (
            <div className="analysis-step-desc">
              <Text type="secondary" style={{ fontSize: 12 }}>
                {step.description}
              </Text>
            </div>
          )}

          <div className="analysis-step-tags">
            {step.dimensions?.map((dim) => (
              <Tag key={`dim-${dim}`} color="purple" variant="filled" style={{ fontSize: 11 }}>
                维度 · {dim}
              </Tag>
            ))}
            {step.metrics?.map((metric) => (
              <Tag key={`metric-${metric}`} color="cyan" variant="filled" style={{ fontSize: 11 }}>
                指标 · {metric}
              </Tag>
            ))}
            {typeof step.rowCount === 'number' && step.status !== 'pending' && (
              <Tag variant="filled" style={{ fontSize: 11 }}>
                {step.rowCount} 行
              </Tag>
            )}
          </div>
        </div>
      </div>
    );

    return {
      key: step.step_id,
      label: header,
      children: (
        <div className="analysis-step-body">
          {step.status === 'running' && !sql && (
            <div className="analysis-step-running-hint">
              <Spin size="small" />
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                正在生成该步骤的 SQL…
              </Text>
            </div>
          )}

          {step.retries && step.retries.length > 0 && (
            <div className="analysis-step-retries">
              {step.retries.map((retry) => (
                <div className="analysis-step-retry-item" key={retry.attempt}>
                  <Tag color={retry.mode === 'rewrite' ? 'gold' : 'default'} style={{ fontSize: 11 }}>
                    {retry.mode === 'rewrite' ? '按报错重写' : '原样重试'}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    第 {retry.attempt}
                    {retry.maxAttempts ? `/${retry.maxAttempts}` : ''} 次尝试
                  </Text>
                  {retry.previousError && (
                    <div className="analysis-step-retry-error">
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        上次报错：
                      </Text>
                      <span className="analysis-step-retry-error-text">
                        {retry.previousError}
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {step.error && (
            <Paragraph
              style={{
                fontFamily: 'monospace',
                background: '#fff1f0',
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid #ffa39e',
                marginBottom: 12,
                fontSize: 12,
                whiteSpace: 'pre-wrap',
              }}
            >
              {step.error}
            </Paragraph>
          )}

          {sql && (
            <div style={{ marginBottom: 12 }}>
              <SqlViewer sql={sql} isStreaming={step.status === 'running' && !step.sql} />
            </div>
          )}

          {step.rows && step.rows.length > 0 && (
            <div className="analysis-step-result">
              <div className="analysis-step-result-title">
                <Text strong style={{ fontSize: 13 }}>
                  步骤查询结果
                </Text>
              </div>
              <StepResultTable columns={step.columns} rows={step.rows} />
            </div>
          )}

          {!hasDetail && step.status !== 'running' && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              该步骤没有可展示的细节。
            </Text>
          )}
        </div>
      ),
    };
  });

  return (
    <div className="analysis-step-list">
      <div className="analysis-section-title">
        <Text strong style={{ fontSize: 14 }}>
          执行计划
        </Text>
        <Tag style={{ marginLeft: 8 }}>
          共 {steps.length} 步
        </Tag>
      </div>

      <Collapse
        items={items}
        activeKey={activeKeys}
        onChange={(keys) =>
          setActiveKeys(Array.isArray(keys) ? (keys as string[]) : [keys as string])
        }
        expandIcon={({ isActive }) => (
          <RightOutlined
            style={{
              fontSize: 11,
              color: '#8c8c8c',
              transform: isActive ? 'rotate(90deg)' : 'none',
              transition: 'transform 0.2s ease',
            }}
          />
        )}
        expandIconPlacement="start"
        bordered={false}
        className="analysis-step-collapse"
      />
    </div>
  );
};
