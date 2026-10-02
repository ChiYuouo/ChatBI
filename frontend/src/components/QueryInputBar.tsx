import React from 'react';
import { Sender } from '@ant-design/x';
import { Segmented, Tooltip } from 'antd';
import { SearchOutlined, PartitionOutlined } from '@ant-design/icons';
import { PromptSuggestions } from './PromptSuggestions';
import { QueryMode } from '../types/chatbi';

interface QueryInputBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  onCancel: () => void;
  loading: boolean;
  disabled?: boolean;
  mode: QueryMode;
  onModeChange: (mode: QueryMode) => void;
}

const PLACEHOLDER: Record<QueryMode, string> = {
  query: '例如：本月各产品线的销售额是多少？',
  analyze: '例如：最近三个月利润变化的主要原因是什么？',
};

export const QueryInputBar: React.FC<QueryInputBarProps> = ({
  value,
  onChange,
  onSubmit,
  onCancel,
  loading,
  disabled,
  mode,
  onModeChange,
}) => {
  const handleSubmit = (text: string) => {
    const trimmed = (text || value || '').trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  const handleSelectPrompt = (promptText: string) => {
    onChange(promptText);
    onSubmit(promptText);
  };

  return (
    <div className="query-input-section">
      <div className="composer-header">
        <div>
          <span className="composer-kicker">NEW ANALYSIS</span>
          <h2>从一个问题开始</h2>
        </div>
        <div className="input-mode-row">
        <Tooltip title="数据查询：直接生成 SQL 并返回结果表格；归因分析：拆解问题、多步查询后给出结论">
          <Segmented
            value={mode}
            onChange={(val) => onModeChange(val as QueryMode)}
            disabled={loading}
            options={[
              {
                label: '数据查询',
                value: 'query',
                icon: <SearchOutlined />,
              },
              {
                label: '归因分析',
                value: 'analyze',
                icon: <PartitionOutlined />,
              },
            ]}
          />
        </Tooltip>
        </div>
      </div>

      <div className="sender-box-wrapper">
        <Sender
          value={value}
          onChange={onChange}
          onSubmit={handleSubmit}
          onCancel={onCancel}
          loading={loading}
          disabled={disabled}
          placeholder={PLACEHOLDER[mode]}
          submitType="enter"
        />
      </div>

      <div className="composer-hint">按 Enter 提交 · 查询过程和结果会保存在当前会话</div>

      <div className="composer-suggestions">
        <PromptSuggestions
          mode={mode}
          onSelectPrompt={handleSelectPrompt}
          disabled={loading || disabled}
        />
      </div>
    </div>
  );
};
