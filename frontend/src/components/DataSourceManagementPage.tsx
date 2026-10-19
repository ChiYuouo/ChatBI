import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Spin, Typography, message } from 'antd';
import { KnowledgeManagement } from './KnowledgeManagement';
import {
  DataSourceConnection, DataSourceSummary, createDataSource, getDataSourceKnowledge,
  listDataSources, saveDataSourceKnowledge, testUnsavedDataSource,
} from '../services/chatbiApi';

type ConnectionForm = DataSourceConnection & { name: string };
const connectionFields = ['host', 'port', 'database', 'user', 'password'] as const;
const connectionSnapshot = (values: Partial<ConnectionForm>) => JSON.stringify(connectionFields.map((key) => values[key]));

/** 添加连接并按数据源维护三类业务知识；普通表结构由后端自动读取。 */
export const DataSourceManagementPage: React.FC<{ onCreated: (source: DataSourceSummary) => void }> = ({ onCreated }) => {
  const [sources, setSources] = useState<DataSourceSummary[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [knowledge, setKnowledge] = useState<Record<string, any>>({});
  const [loadedSourceId, setLoadedSourceId] = useState('');
  const [loadError, setLoadError] = useState('');
  const loadVersion = useRef(0);
  const testVersion = useRef(0);
  const [form] = Form.useForm<ConnectionForm>();
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [connectionTest, setConnectionTest] = useState<{ snapshot: string; tableCount: number } | null>(null);
  const [connectionError, setConnectionError] = useState('');

  useEffect(() => {
    let active = true;
    listDataSources().then((items) => {
      if (active) { setSources(items); setSourceId(items[0]?.source_id || ''); }
    }).catch((error) => { if (active) message.error(error.message); });
    return () => { active = false; };
  }, []);

  const loadKnowledge = async (id: string) => {
    const version = ++loadVersion.current;
    setLoadedSourceId('');
    setLoadError('');
    try {
      const loaded = await getDataSourceKnowledge(id);
      if (version === loadVersion.current) { setKnowledge(loaded); setLoadedSourceId(id); }
    } catch (error: any) {
      if (version === loadVersion.current) setLoadError(error.message || '读取业务知识失败');
    }
  };

  useEffect(() => {
    if (sourceId) void loadKnowledge(sourceId);
    return () => { loadVersion.current += 1; };
  }, [sourceId]);

  const testConnection = async () => {
    let values: ConnectionForm;
    try { values = await form.validateFields([...connectionFields]); }
    catch { return; }
    const version = ++testVersion.current;
    const snapshot = connectionSnapshot(values);
    setTesting(true); setConnectionTest(null); setConnectionError('');
    try {
      const result = await testUnsavedDataSource(values);
      // 请求期间连接参数可能已修改，旧结果不能批准新配置。
      if (version === testVersion.current && snapshot === connectionSnapshot(form.getFieldsValue())) {
        setConnectionTest({ snapshot, tableCount: result.visible_tables });
      }
    } catch (error: any) {
      if (version === testVersion.current) setConnectionError(error.message || '连接测试失败');
    } finally { setTesting(false); }
  };

  const addSource = async (values: ConnectionForm) => {
    if (!connectionTest || connectionTest.snapshot !== connectionSnapshot(values)) {
      message.warning('请先测试当前连接，通过后再保存');
      return;
    }
    setSaving(true);
    try {
      const source = await createDataSource(values);
      setSources((items) => [...items, source]);
      setSourceId(source.source_id);
      onCreated(source);
      form.resetFields(); setConnectionTest(null); setConnectionError('');
      message.success('数据源已添加，表结构已自动保存，可以开始查询');
    } catch (error: any) {
      setConnectionTest(null); setConnectionError(error.message || '保存失败，请重新测试');
    } finally { setSaving(false); }
  };

  const saveKnowledge = async (changes: Record<string, any>) => {
    const version = loadVersion.current;
    const saved = await saveDataSourceKnowledge(sourceId, changes);
    if (version === loadVersion.current) setKnowledge(saved);
  };

  return <div className="chatbi-main-container">
    <div className="workspace-heading"><div><div className="workspace-eyebrow">DATA SOURCES</div><h1>数据源管理</h1><p>添加 MySQL 数据源，维护业务规则、错误防护和 SQL 示例。</p></div></div>
    <Card title="添加数据源" style={{ marginBottom: 20 }}>
      <Form form={form} layout="vertical" disabled={saving} initialValues={{ port: 3306 }} onFinish={addSource}
        onValuesChange={(changed) => {
          if (connectionFields.some((key) => key in changed)) {
            testVersion.current += 1; setConnectionTest(null); setConnectionError('');
          }
        }}>
        <Space align="start" wrap>
          <Form.Item name="name" label="显示名称" rules={[{ required: true, whitespace: true }]}><Input placeholder="例如：运营数据库" /></Form.Item>
          <Form.Item name="host" label="主机地址" rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
          <Form.Item name="port" label="端口" rules={[{ required: true }]}><InputNumber min={1} max={65535} /></Form.Item>
          <Form.Item name="database" label="数据库名" rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
          <Form.Item name="user" label="只读账号" rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item>
        </Space>
        <Space wrap>
          <Button htmlType="button" loading={testing} onClick={testConnection}>测试连接</Button>
          <Button type="primary" htmlType="submit" loading={saving} disabled={!connectionTest || testing}>保存数据源</Button>
          <Typography.Text type="secondary">先测试再保存，表结构自动读取，无需手动选表。</Typography.Text>
        </Space>
      </Form>
      {connectionTest && <Alert type="success" showIcon title={`测试通过，可读取 ${connectionTest.tableCount} 张普通表。点击“保存数据源”完成添加。`} style={{ marginTop: 16 }} />}
      {connectionError && <Alert type="error" showIcon title={connectionError} style={{ marginTop: 16 }} />}
    </Card>
    <Card title="业务知识">
      <Select aria-label="选择配置的数据源" style={{ width: 320, marginBottom: 20 }} value={sourceId || undefined} onChange={setSourceId}
        options={sources.map((source) => ({ value: source.source_id, label: source.name }))} />
      {sourceId && loadedSourceId === sourceId
        ? <KnowledgeManagement key={sourceId} knowledge={knowledge} onSave={saveKnowledge} />
        : loadError ? <Alert type="error" showIcon title={loadError} action={<Button onClick={() => loadKnowledge(sourceId)}>重试</Button>} />
          : sourceId ? <Spin tip="正在读取业务知识"><div style={{ minHeight: 120 }} /></Spin>
            : <Typography.Text type="secondary">请选择数据源。</Typography.Text>}
    </Card>
  </div>;
};
