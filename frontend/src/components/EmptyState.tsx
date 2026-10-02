import React from 'react';
import { BarChartOutlined, ArrowUpOutlined } from '@ant-design/icons';

export const EmptyState: React.FC = () => (
  <div className="empty-state-container">
    <div className="empty-state-icon"><BarChartOutlined /></div>
    <h3>还没有分析记录</h3>
    <p>在上方输入问题，数据查询和归因分析的结果会集中显示在这里。</p>
    <div className="empty-state-tip"><ArrowUpOutlined /> 从上方的问题输入框开始</div>
  </div>
);
