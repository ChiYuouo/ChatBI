import React from 'react';
import { Steps } from 'antd';
import {
  PartitionOutlined,
  ApartmentOutlined,
  DatabaseOutlined,
  MergeCellsOutlined,
  FileDoneOutlined,
} from '@ant-design/icons';
import { AnalysisStatus } from '../types/chatbi';

interface AnalysisStageBarProps {
  status: AnalysisStatus;
  totalSteps?: number;
  executedSteps?: number;
}

const STAGE_ORDER: AnalysisStatus[] = [
  'decomposing',
  'planning',
  'executing',
  'summarizing',
  'reporting',
];

/** 把链路状态映射为阶段下标，便于 Steps 高亮 */
function resolveCurrentIndex(status: AnalysisStatus): number {
  if (status === 'success') return STAGE_ORDER.length;
  if (status === 'error' || status === 'cancelled') return -1;
  const index = STAGE_ORDER.indexOf(status);
  return index === -1 ? 0 : index;
}

export const AnalysisStageBar: React.FC<AnalysisStageBarProps> = ({
  status,
  totalSteps,
  executedSteps = 0,
}) => {
  const current = resolveCurrentIndex(status);
  const isFailed = status === 'error' || status === 'cancelled';

  const executingDesc =
    status === 'executing' && totalSteps
      ? `已执行 ${executedSteps}/${totalSteps} 步`
      : undefined;

  return (
    <div className="analysis-stage-bar">
      <Steps
        size="small"
        current={isFailed ? 0 : current}
        status={isFailed ? 'error' : 'process'}
        items={[
          {
            title: '问题拆解',
            content: status === 'decomposing' ? '正在拆解分析意图' : undefined,
            icon: <PartitionOutlined />,
          },
          {
            title: '执行计划',
            content: status === 'planning' ? '正在编排子步骤' : undefined,
            icon: <ApartmentOutlined />,
          },
          {
            title: '多步执行',
            content: executingDesc,
            icon: <DatabaseOutlined />,
          },
          {
            title: '结果汇总',
            content: status === 'summarizing' ? '正在收敛各步结果' : undefined,
            icon: <MergeCellsOutlined />,
          },
          {
            title: '归因报告',
            content: status === 'reporting' ? '正在生成结论' : undefined,
            icon: <FileDoneOutlined />,
          },
        ]}
      />
    </div>
  );
};
