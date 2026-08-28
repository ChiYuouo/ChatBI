import React from 'react';
import { Sender } from '@ant-design/x';
import { PromptSuggestions } from './PromptSuggestions';

interface QueryInputBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  onCancel: () => void;
  loading: boolean;
  disabled?: boolean;
}

export const QueryInputBar: React.FC<QueryInputBarProps> = ({
  value,
  onChange,
  onSubmit,
  onCancel,
  loading,
  disabled,
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
      <div className="sender-box-wrapper">
        <Sender
          value={value}
          onChange={onChange}
          onSubmit={handleSubmit}
          onCancel={onCancel}
          loading={loading}
          disabled={disabled}
          placeholder="输入您的业务分析问题（例如：上个月销售额是多少？），按 Enter 或点击右侧按钮发起查询"
          submitType="enter"
        />
      </div>

      <div style={{ marginTop: 14 }}>
        <PromptSuggestions
          onSelectPrompt={handleSelectPrompt}
          disabled={loading || disabled}
        />
      </div>
    </div>
  );
};
