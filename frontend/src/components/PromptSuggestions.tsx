import React from 'react';
import { Space, Typography, Tag } from 'antd';
import {
  DollarOutlined,
  ShoppingOutlined,
  LineChartOutlined,
  UsergroupAddOutlined,
  FireOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

interface PromptSuggestionsProps {
  onSelectPrompt: (prompt: string) => void;
  disabled?: boolean;
}

const SAMPLE_PROMPTS = [
  {
    key: '1',
    icon: <DollarOutlined style={{ color: '#52c41a' }} />,
    text: '上个月销售额是多少？',
  },
  {
    key: '2',
    icon: <FireOutlined style={{ color: '#f5222d' }} />,
    text: '查询销售额排名前 10 的商品及分类',
  },
  {
    key: '3',
    icon: <LineChartOutlined style={{ color: '#1677ff' }} />,
    text: '统计近 30 天每天的订单量与客单价趋势',
  },
  {
    key: '4',
    icon: <UsergroupAddOutlined style={{ color: '#722ed1' }} />,
    text: '累计消费金额最高的用户 Top 5',
  },
];

export const PromptSuggestions: React.FC<PromptSuggestionsProps> = ({
  onSelectPrompt,
  disabled,
}) => {
  return (
    <div className="prompt-suggestions-wrapper">
      <div className="prompt-header" style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 13, fontWeight: 500 }}>
          💡 常用业务指标快捷查询（点击直接发起）：
        </Text>
      </div>

      <Space wrap size={[8, 8]}>
        {SAMPLE_PROMPTS.map((item) => (
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
