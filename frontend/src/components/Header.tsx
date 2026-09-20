import React from 'react';
import { Space, Typography, Tag, Button, Tooltip } from 'antd';
import {
  DatabaseOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  LogoutOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { HealthState } from '../types/chatbi';

const { Title, Text } = Typography;

interface HeaderProps {
  health: HealthState;
  onRefreshHealth: () => void;
  historyCount: number;
  /** 退出登录 */
  onLogout: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  onRefreshHealth,
  historyCount,
  onLogout,
}) => {
  const getHealthBadge = () => {
    if (health.status === 'checking') {
      return (
        <Tag icon={<LoadingOutlined />} color="processing">
          服务连接中
        </Tag>
      );
    }
    if (health.status === 'ok' && health.databaseConnected) {
      return (
        <Tooltip title="后端服务正常，数据库已连通">
          <Tag icon={<CheckCircleOutlined />} color="success" style={{ cursor: 'pointer' }} onClick={onRefreshHealth}>
            系统正常 (DB 在线)
          </Tag>
        </Tooltip>
      );
    }
    if (health.status === 'ok' && !health.databaseConnected) {
      return (
        <Tooltip title="API 正常但数据库连接异常">
          <Tag icon={<CloseCircleOutlined />} color="warning" style={{ cursor: 'pointer' }} onClick={onRefreshHealth}>
            数据库异常
          </Tag>
        </Tooltip>
      );
    }
    return (
      <Tooltip title={health.message || '后端服务未启动或连接失败'}>
        <Tag icon={<CloseCircleOutlined />} color="error" style={{ cursor: 'pointer' }} onClick={onRefreshHealth}>
          服务离线
        </Tag>
      </Tooltip>
    );
  };

  return (
    <header className="chatbi-header">
      <div className="header-brand">
        <div className="brand-logo">
          <DatabaseOutlined style={{ fontSize: 22, color: '#1677ff' }} />
        </div>
        <div className="brand-text">
          <Title level={4} style={{ margin: 0, fontWeight: 700, letterSpacing: '-0.3px' }}>
            ChatBI 数据分析工作台
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            基于自然语言的 Text-to-SQL 智能查询引擎
          </Text>
        </div>
      </div>

      <Space size="middle">
        {getHealthBadge()}
        {historyCount > 0 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {historyCount} 条记录
          </Text>
        )}
        <Tooltip title="退出登录">
          <Button
            type="text"
            size="small"
            icon={<LogoutOutlined />}
            onClick={onLogout}
            style={{ color: '#8c8c8c' }}
          >
            退出
          </Button>
        </Tooltip>
      </Space>
    </header>
  );
};
