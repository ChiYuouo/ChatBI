import React from 'react';
import { ThoughtChain, ThoughtChainProps } from '@ant-design/x';
import {
  LoadingOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  CodeOutlined,
  DatabaseOutlined,
  BarChartOutlined,
} from '@ant-design/icons';
import { QueryStatus } from '../types/chatbi';

interface QueryStatusChainProps {
  status: QueryStatus;
  sqlDurationMs?: number;
  totalDurationMs?: number;
  rowCount?: number;
  error?: string;
}

export const QueryStatusChain: React.FC<QueryStatusChainProps> = ({
  status,
  sqlDurationMs,
  totalDurationMs,
  rowCount,
  error,
}) => {
  const getStepStatus = (step: 1 | 2 | 3): 'loading' | 'success' | 'error' | 'abort' | undefined => {
    if (status === 'cancelled') {
      return 'abort';
    }

    if (error) {
      if (status === 'generating_sql' && step === 1) return 'error';
      if (status === 'executing_query' && step === 2) return 'error';
      return 'error';
    }

    if (status === 'generating_sql') {
      if (step === 1) return 'loading';
      return undefined;
    }

    if (status === 'executing_query') {
      if (step === 1) return 'success';
      if (step === 2) return 'loading';
      return undefined;
    }

    if (status === 'success') {
      return 'success';
    }

    return undefined;
  };

  const items: ThoughtChainProps['items'] = [
    {
      key: 'step1',
      title: '意图理解与 SQL 生成',
      status: getStepStatus(1),
      description:
        status === 'generating_sql'
          ? 'LLM 正在分析表结构与业务指标并编写 SQL...'
          : sqlDurationMs
          ? `SQL 生成完成 (耗时 ${sqlDurationMs}ms)`
          : 'SQL 生成完成',
      icon:
        getStepStatus(1) === 'loading' ? (
          <LoadingOutlined style={{ color: '#1677ff' }} />
        ) : getStepStatus(1) === 'success' ? (
          <CheckCircleFilled style={{ color: '#52c41a' }} />
        ) : getStepStatus(1) === 'error' ? (
          <CloseCircleFilled style={{ color: '#ff4d4f' }} />
        ) : (
          <CodeOutlined />
        ),
    },
    {
      key: 'step2',
      title: '数据库执行与权限验证',
      status: getStepStatus(2),
      description:
        status === 'executing_query'
          ? '正在向数据库执行 SQL 并检索记录...'
          : status === 'success'
          ? 'SQL 执行完成，数据返回正常'
          : error && status !== 'generating_sql'
          ? 'SQL 执行失败'
          : '等待 SQL 生成后执行',
      icon:
        getStepStatus(2) === 'loading' ? (
          <LoadingOutlined style={{ color: '#1677ff' }} />
        ) : getStepStatus(2) === 'success' ? (
          <CheckCircleFilled style={{ color: '#52c41a' }} />
        ) : getStepStatus(2) === 'error' ? (
          <CloseCircleFilled style={{ color: '#ff4d4f' }} />
        ) : (
          <DatabaseOutlined />
        ),
    },
    {
      key: 'step3',
      title: '数据装配与表格渲染',
      status: getStepStatus(3),
      description:
        status === 'success'
          ? `已成功装配 ${rowCount ?? 0} 条数据结果 (总耗时 ${
              totalDurationMs ? `${totalDurationMs}ms` : ''
            })`
          : '准备渲染数据视图',
      icon:
        getStepStatus(3) === 'success' ? (
          <CheckCircleFilled style={{ color: '#52c41a' }} />
        ) : (
          <BarChartOutlined />
        ),
    },
  ];

  return (
    <div className="status-chain-wrapper">
      <ThoughtChain items={items} />
    </div>
  );
};
