import React from 'react';
import { Button, Tooltip } from 'antd';
import {
  LogoutOutlined,
  DownOutlined,
} from '@ant-design/icons';
import { HealthState } from '../types/chatbi';

interface HeaderProps {
  health: HealthState;
  onRefreshHealth: () => void;
  historyCount: number;
  /** 退出登录 */
  onLogout: () => void;
  view: 'analysis' | 'users';
}

export const Header: React.FC<HeaderProps> = ({
  health,
  onRefreshHealth,
  historyCount,
  onLogout,
  view,
}) => {
  const getHealthBadge = () => {
    if (health.status === 'checking') {
      return <span className="health-indicator checking">连接中</span>;
    }
    if (health.status === 'ok' && health.databaseConnected) {
      return (
        <Tooltip title="后端服务正常，数据库已连通">
          <button className="health-indicator online" onClick={onRefreshHealth}>
            数据服务正常
          </button>
        </Tooltip>
      );
    }
    if (health.status === 'ok' && !health.databaseConnected) {
      return (
        <Tooltip title="API 正常但数据库连接异常">
          <button className="health-indicator warning" onClick={onRefreshHealth}>数据库异常</button>
        </Tooltip>
      );
    }
    return (
      <Tooltip title={health.message || '后端服务未启动或连接失败'}>
        <button className="health-indicator offline" onClick={onRefreshHealth}>服务离线</button>
      </Tooltip>
    );
  };

  return (
    <header className="chatbi-header">
      <div className="header-location">
        <span>工作台</span>
        <span className="header-location-separator">/</span>
        <strong>{view === 'users' ? '用户授权' : '智能分析'}</strong>
      </div>
      <div className="header-actions">
        {getHealthBadge()}
        {view === 'analysis' && <span className="header-activity">本页 {historyCount} 条记录</span>}
        <span className="header-divider" />
        <div className="account-avatar" aria-label="当前账户">我</div>
        <Tooltip title="退出登录">
          <Button
            type="text"
            size="small"
            icon={<LogoutOutlined />}
            onClick={onLogout}
            className="header-logout"
          >
            退出 <DownOutlined className="header-logout-chevron" />
          </Button>
        </Tooltip>
      </div>
    </header>
  );
};
