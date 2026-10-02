import React from 'react';
import { Button, Tooltip, Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined, MessageOutlined, AppstoreOutlined, DatabaseOutlined } from '@ant-design/icons';
import { SessionSummary } from '../services/chatbiApi';

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onNewSession: () => void;
}

/** 格式化「最近活动」时间为易读的相对/简短形式 */
function formatTime(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

export const SessionSidebar: React.FC<SessionSidebarProps> = ({
  sessions,
  activeSessionId,
  onSelect,
  onDelete,
  onNewSession,
}) => {
  return (
    <aside className="session-sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-mark"><DatabaseOutlined /></div>
        <div><strong>ChatBI</strong><span>DATA WORKSPACE</span></div>
      </div>
      <div className="sidebar-section-label">工作空间</div>
      <div className="sidebar-nav-active"><AppstoreOutlined /> 智能分析</div>
      <div className="sidebar-section-label sidebar-history-label">最近会话</div>
      <Button
        block
        type="primary"
        icon={<PlusOutlined />}
        onClick={onNewSession}
        className="sidebar-new-button"
      >
        新建分析
      </Button>

      {sessions.length === 0 ? (
        <div className="session-empty">
          还没有历史会话
          <br />
          提问后会自动保存在这里
        </div>
      ) : (
        <ul className="session-list">
          {sessions.map((session) => {
            const active = session.session_id === activeSessionId;
            return (
              <li
                key={session.session_id}
                className={`session-item${active ? ' active' : ''}`}
                onClick={() => onSelect(session.session_id)}
              >
                <MessageOutlined className="session-icon" />
                <div className="session-item-body">
                  <div className="session-item-title" title={session.title}>
                    {session.title}
                  </div>
                  <div className="session-item-meta">
                    {session.turns} 轮 · {formatTime(session.updated_at)}
                  </div>
                </div>
                <Popconfirm
                  title="删除该会话及其全部记录？"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={(e) => {
                    e?.stopPropagation();
                    onDelete(session.session_id);
                  }}
                  onCancel={(e) => e?.stopPropagation()}
                >
                  <Tooltip title="删除此会话">
                    <Button
                      type="text"
                      size="small"
                      icon={<DeleteOutlined />}
                      onClick={(e) => e.stopPropagation()}
                      style={{ color: '#b0b7c3' }}
                    />
                  </Tooltip>
                </Popconfirm>
              </li>
            );
          })}
        </ul>
      )}
      <div className="sidebar-footer">
        <span className="sidebar-footer-dot" />
        数据仅供授权用户访问
      </div>
    </aside>
  );
};
