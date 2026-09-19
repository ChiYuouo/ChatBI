import React from 'react';
import { Welcome } from '@ant-design/x';
import {
  DatabaseTwoTone,
  CodeTwoTone,
  FundTwoTone,
  ExperimentTwoTone,
} from '@ant-design/icons';
import { Typography, Row, Col, Card } from 'antd';

const { Text } = Typography;

export const EmptyState: React.FC = () => {
  return (
    <div className="empty-state-container">
      <Welcome
        icon={<DatabaseTwoTone style={{ fontSize: 48 }} />}
        title="欢迎使用 ChatBI 智能数据分析"
        description="选择「数据查询」直接生成 SQL 并查看结果表格；选择「归因分析」则自动拆解问题、多步查询，最终给出可解释的归因结论。"
      />

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col xs={24} md={8}>
          <Card size="small" className="feature-intro-card" variant="borderless">
            <div className="feature-icon">
              <CodeTwoTone twoToneColor="#1677ff" style={{ fontSize: 24 }} />
            </div>
            <Text strong style={{ display: 'block', margin: '8px 0 4px' }}>
              实时 SQL 生成与审查
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              SSE 流式实时打印 SQL，语法高亮，清晰透明。
            </Text>
          </Card>
        </Col>

        <Col xs={24} md={8}>
          <Card size="small" className="feature-intro-card" variant="borderless">
            <div className="feature-icon">
              <ExperimentTwoTone twoToneColor="#722ed1" style={{ fontSize: 24 }} />
            </div>
            <Text strong style={{ display: 'block', margin: '8px 0 4px' }}>
              多步归因分析
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              拆解问题并逐步下钻，输出归因结论与行动建议。
            </Text>
          </Card>
        </Col>

        <Col xs={24} md={8}>
          <Card size="small" className="feature-intro-card" variant="borderless">
            <div className="feature-icon">
              <FundTwoTone twoToneColor="#52c41a" style={{ fontSize: 24 }} />
            </div>
            <Text strong style={{ display: 'block', margin: '8px 0 4px' }}>
              交互式数据表格
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              支持按字段快速排序、数据分页、一键导出 CSV。
            </Text>
          </Card>
        </Col>
      </Row>
    </div>
  );
};
