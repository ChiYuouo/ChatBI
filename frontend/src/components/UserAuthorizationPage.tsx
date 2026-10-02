import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Input, Select, Space, Table, Tag, message } from 'antd';
import { AuthUser, UnauthorizedError, authorizeUser, listUsers } from '../services/chatbiApi';

const roleLabels: Record<AuthUser['role'], string> = {
  pending: '待授权',
  admin: '管理员',
  finance: '财务',
  sales: '销售',
};

interface Props {
  currentUserId: string;
  onUnauthorized: () => void;
}

export const UserAuthorizationPage: React.FC<Props> = ({ currentUserId, onUnauthorized }) => {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [role, setRole] = useState<AuthUser['role']>('sales');
  const [region, setRegion] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setUsers(await listUsers());
    } catch (err) {
      if (err instanceof UnauthorizedError) onUnauthorized();
      else setError(err instanceof Error ? err.message : '用户列表加载失败');
    } finally {
      setLoading(false);
    }
  }, [onUnauthorized]);

  useEffect(() => { void load(); }, [load]);

  const startEdit = (user: AuthUser) => {
    setEditingId(user.user_id);
    setRole(user.role === 'pending' ? 'sales' : user.role);
    setRegion(user.region || '');
    setError('');
  };

  const save = async () => {
    if (!editingId) return;
    const normalizedRegion = role === 'sales' ? region.trim() : null;
    if (role === 'sales' && (!normalizedRegion || normalizedRegion.length > 50)) {
      setError('销售角色需要填写 1～50 字的区域');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const updated = await authorizeUser(editingId, role, normalizedRegion);
      setUsers((previous) => previous.map((user) => user.user_id === editingId ? updated : user));
      setEditingId(null);
      message.success('授权已保存');
    } catch (err) {
      if (err instanceof UnauthorizedError) onUnauthorized();
      else setError(err instanceof Error ? err.message : '授权保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="chatbi-main-container user-authorization-page">
      <div className="workspace-heading">
        <div>
          <div className="workspace-eyebrow">WORKSPACE / ACCESS</div>
          <h1>用户授权</h1>
          <p>为注册用户分配角色。销售角色还需要指定可访问的区域。</p>
        </div>
        <Button onClick={() => void load()} loading={loading}>刷新列表</Button>
      </div>
      {error && <Alert type="error" message={error} showIcon closable onClose={() => setError('')} style={{ marginBottom: 16 }} />}
      <div className="user-authorization-card">
        <Table<AuthUser>
          rowKey="user_id"
          dataSource={users}
          loading={loading}
          pagination={{ pageSize: 10 }}
          scroll={{ x: 720 }}
          columns={[
            { title: '用户名', dataIndex: 'username', key: 'username' },
            {
              title: '角色', key: 'role',
              render: (_, user) => editingId === user.user_id ? (
                <Select<AuthUser['role']>
                  value={role}
                  onChange={(next) => setRole(next)}
                  style={{ width: 130 }}
                  options={Object.entries(roleLabels).map(([value, label]) => ({ value, label }))}
                />
              ) : <Tag color={user.role === 'pending' ? 'orange' : 'green'}>{roleLabels[user.role]}</Tag>,
            },
            {
              title: '区域', key: 'region',
              render: (_, user) => editingId === user.user_id && role === 'sales' ? (
                <Input value={region} onChange={(event) => setRegion(event.target.value)} maxLength={50} placeholder="例如：欧洲" style={{ width: 180 }} />
              ) : editingId === user.user_id ? '不适用' : (user.region || '—'),
            },
            {
              title: '操作', key: 'action',
              render: (_, user) => user.user_id === currentUserId ? '当前账号' : editingId === user.user_id ? (
                <Space>
                  <Button type="primary" onClick={() => void save()} loading={saving}>保存</Button>
                  <Button onClick={() => setEditingId(null)} disabled={saving}>取消</Button>
                </Space>
              ) : <Button type="link" onClick={() => startEdit(user)} disabled={editingId !== null}>设置权限</Button>,
            },
          ]}
        />
      </div>
    </main>
  );
};
