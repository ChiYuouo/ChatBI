import React from 'react';
import { Welcome } from '@ant-design/x';
import { DatabaseTwoTone, CodeTwoTone, FundTwoTone } from '@ant-design/icons';
import { Typography, Row, Col, Card } from 'antd';

const { Text } = Typography;

export const EmptyState: React.FC = () => {
  return (
    <div className="empty-state-container">
      <Welcome
        icon={<DatabaseTwoTone style={{ fontSize: 48 }} />}
        title="欢迎使用 ChatBI 智能数据分析"
        description="无需编写复杂 SQL，直接输入您的业务分析问题，系统将自动生成查询语句并在右侧/下方呈现结构化数据表。"
      />

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col xs={24} md={8}>
          <Card size="small" className="feature-intro-card" bordered={false}>
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
          <Card size="small" className="feature-intro-card" bordered={false}>
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

        <Col xs={24} md={8}>
          <Card size="small" className="feature-intro-card" bordered={false}>
            <div className="feature-icon">
              <DatabaseTwoTone twoToneColor="#722ed1" style={{ fontSize: 24 }} />
            </div>
            <Text strong style={{ display: 'block', margin: '8px 0 4px' }}>
              安全隔离与防护
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              内置只读限制与权限策略，保障数据库安全。
            </Text>
          </Card>
        </Col>
      </Row>
    </div>
  );
};
