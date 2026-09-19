import React from 'react';
import { Tag, Typography, Button, Tooltip, message, Empty } from 'antd';
import {
  BulbOutlined,
  AimOutlined,
  LineChartOutlined,
  ThunderboltOutlined,
  CopyOutlined,
  DownloadOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { AnalysisReport } from '../types/chatbi';

const { Text, Paragraph } = Typography;

interface AnalysisReportViewProps {
  report?: AnalysisReport;
  /** 报告尚未生成时的占位提示 */
  pending?: boolean;
}

/** 带左侧色条的要点列表，用于承载归因结论这类需要强调的内容 */
const BulletList: React.FC<{
  items: string[];
  accent: string;
  emptyHint: string;
}> = ({ items, accent, emptyHint }) => {
  if (!items || items.length === 0) {
    return (
      <Text type="secondary" style={{ fontSize: 13 }}>
        {emptyHint}
      </Text>
    );
  }

  return (
    <ul className="analysis-bullet-list">
      {items.map((item, index) => (
        <li key={index} style={{ borderLeftColor: accent }}>
          {item}
        </li>
      ))}
    </ul>
  );
};

const Section: React.FC<{
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
  highlight?: boolean;
}> = ({ icon, title, children, highlight }) => (
  <div className={`analysis-report-section${highlight ? ' is-highlight' : ''}`}>
    <div className="analysis-report-section-title">
      {icon}
      <span>{title}</span>
    </div>
    <div className="analysis-report-section-body">{children}</div>
  </div>
);

export const AnalysisReportView: React.FC<AnalysisReportViewProps> = ({
  report,
  pending,
}) => {
  if (!report) {
    if (!pending) return null;
    return (
      <div className="analysis-report-pending">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <Text type="secondary" style={{ fontSize: 13 }}>
              正在根据各步骤结果生成归因报告…
            </Text>
          }
        />
      </div>
    );
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(report.markdown || '');
      message.success('报告 Markdown 已复制到剪贴板');
    } catch {
      message.error('复制失败，请手动复制');
    }
  };

  const handleDownload = () => {
    const content = report.markdown || '';
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `attribution_report_${new Date().toISOString().slice(0, 10)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="analysis-report">
      <div className="analysis-section-title analysis-report-header">
        <div>
          <FileTextOutlined style={{ color: '#1677ff', marginRight: 6 }} />
          <Text strong style={{ fontSize: 14 }}>
            归因分析报告
          </Text>
        </div>

        <div className="analysis-report-actions">
          <Tooltip title="复制报告 Markdown">
            <Button size="small" type="text" icon={<CopyOutlined />} onClick={handleCopy}>
              复制
            </Button>
          </Tooltip>
          <Tooltip title="下载 Markdown 报告">
            <Button size="small" type="text" icon={<DownloadOutlined />} onClick={handleDownload}>
              下载
            </Button>
          </Tooltip>
        </div>
      </div>

      <div className="analysis-report-card">
        <div className="analysis-report-title">
          <Text strong style={{ fontSize: 16 }}>
            {report.title}
          </Text>
        </div>

        <Section icon={<AimOutlined style={{ color: '#1677ff' }} />} title="执行摘要">
          <Paragraph style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>
            {report.executive_summary || '—'}
          </Paragraph>
        </Section>

        <Section icon={<BulbOutlined style={{ color: '#faad14' }} />} title="关键发现">
          <BulletList
            items={report.key_findings}
            accent="#faad14"
            emptyHint="当前结果不足，暂时无法提炼关键发现。"
          />
        </Section>

        <Section
          icon={<ThunderboltOutlined style={{ color: '#f5222d' }} />}
          title="归因分析"
          highlight
        >
          <BulletList
            items={report.root_causes}
            accent="#f5222d"
            emptyHint="暂未定位到明确的驱动因素。"
          />
        </Section>

        <Section icon={<LineChartOutlined style={{ color: '#52c41a' }} />} title="趋势判断">
          <Paragraph style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>
            {report.trend_judgment || '—'}
          </Paragraph>
        </Section>

        <Section icon={<ThunderboltOutlined style={{ color: '#722ed1' }} />} title="行动建议">
          <BulletList
            items={report.action_suggestions}
            accent="#722ed1"
            emptyHint="暂无行动建议。"
          />
        </Section>
      </div>
    </div>
  );
};
