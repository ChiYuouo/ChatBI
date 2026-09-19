import React from 'react';
import { Space, Typography, Tag } from 'antd';
import {
  DollarOutlined,
  ShoppingOutlined,
  LineChartOutlined,
  UsergroupAddOutlined,
  FallOutlined,
  AlertOutlined,
  RiseOutlined,
  ClusterOutlined,
} from '@ant-design/icons';
import { QueryMode } from '../types/chatbi';

const { Text } = Typography;

interface PromptSuggestionsProps {
  onSelectPrompt: (prompt: string) => void;
  disabled?: boolean;
  mode: QueryMode;
}

interface Suggestion {
  key: string;
  icon: React.ReactNode;
  text: string;
}

const QUERY_PROMPTS: Suggestion[] = [
  {
    key: 'q1',
    icon: <DollarOutlined style={{ color: '#52c41a' }} />,
    text: '上个月销售额是多少？',
  },
  {
    key: 'q2',
    icon: <ShoppingOutlined style={{ color: '#f5222d' }} />,
    text: '按产品线统计各区域的净销售额',
  },
  {
    key: 'q3',
    icon: <LineChartOutlined style={{ color: '#1677ff' }} />,
    text: '统计各客户类型的订单量和平均客单价',
  },
  {
    key: 'q4',
    icon: <UsergroupAddOutlined style={{ color: '#722ed1' }} />,
    text: '查询销售额排名前三的产品线',
  },
];

const ANALYZE_PROMPTS: Suggestion[] = [
  {
    key: 'a1',
    icon: <FallOutlined style={{ color: '#f5222d' }} />,
    text: '最近三个月利润为什么下降？',
  },
  {
    key: 'a2',
    icon: <AlertOutlined style={{ color: '#fa8c16' }} />,
    text: '哪些产品线的成本上升最快，主要原因是什么？',
  },
  {
    key: 'a3',
    icon: <RiseOutlined style={{ color: '#52c41a' }} />,
    text: '分析各区域销售趋势及背后的驱动因素',
  },
  {
    key: 'a4',
    icon: <ClusterOutlined style={{ color: '#722ed1' }} />,
    text: '费用结构中哪一项增长最异常，为什么？',
  },
];

export const PromptSuggestions: React.FC<PromptSuggestionsProps> = ({
  onSelectPrompt,
  disabled,
  mode,
}) => {
  const isAnalyze = mode === 'analyze';
  const prompts = isAnalyze ? ANALYZE_PROMPTS : QUERY_PROMPTS;

  return (
    <div className="prompt-suggestions-wrapper">
      <div className="prompt-header" style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 13, fontWeight: 500 }}>
          {isAnalyze
            ? '🔍 归因分析示例（点击直接发起，耗时较长）：'
            : '💡 常用业务指标快捷查询（点击直接发起）：'}
        </Text>
      </div>

      <Space wrap size={[8, 8]}>
        {prompts.map((item) => (
          <Tag
            key={item.key}
            icon={item.icon}
            color="default"
            style={{
              padding: '6px 12px',
              borderRadius: 16,
              cursor: disabled ? 'not-allowed' : 'pointer',
              fontSize: 13,
              userSelect: 'none',
              transition: 'all 0.2s ease',
              border: '1px solid #d9d9d9',
              background: '#fafafa',
            }}
            onClick={() => {
              if (!disabled) {
                onSelectPrompt(item.text);
              }
            }}
            className="prompt-tag-item"
          >
            {item.text}
          </Tag>
        ))}
      </Space>
    </div>
  );
};
