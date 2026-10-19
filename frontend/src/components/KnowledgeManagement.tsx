import React, { useState } from 'react';
import { Alert, Button, Drawer, Form, Input, Popconfirm, Space, Table, Tabs, message } from 'antd';

type Knowledge = Record<string, any>;
type Entry = Record<string, any>;
type Commit = (patch: Knowledge) => Promise<boolean>;
const required = (label: string) => [{ required: true, whitespace: true, message: `请填写${label}` }];
const pagination = { defaultPageSize: 8, showSizeChanger: true, pageSizeOptions: [8, 16, 32], showTotal: (total: number) => `共 ${total} 条` };

/** 每次只编辑一条，确认后直接持久化；取消新增不会留下空记录。 */
const EntryList: React.FC<{
  items: Entry[]; field: string; label: string; examples?: boolean; saving: boolean; commit: Commit;
}> = ({ items, field, label, examples, saving, commit }) => {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<number | null>(null);
  const [form] = Form.useForm();
  const legacy = editing !== null && editing >= 0 && items[editing]?.kind === 'legacy';
  const rows = items.map((item, index): Entry => ({ ...item, index })).filter((item) =>
    Object.values(item).some((value) => typeof value === 'string' && value.toLowerCase().includes(query.trim().toLowerCase())));
  const open = (index: number) => {
    form.resetFields();
    form.setFieldsValue(index < 0 ? {} : items[index]);
    setEditing(index);
  };
  const save = async (values: Entry) => {
    if (editing === null) return;
    const updated = { ...(items[editing] || {}), ...values };
    const next = editing < 0 ? [...items, updated] : items.map((item, i) => i === editing ? updated : item);
    if (await commit({ [field]: next })) setEditing(null);
  };
  return <>
    <div className="knowledge-toolbar">
      <Input.Search allowClear placeholder={`搜索${label}`} value={query} onChange={(e) => { setQuery(e.target.value); setPage(1); }} />
      <Button type="primary" onClick={() => open(-1)} disabled={saving}>添加{label}</Button>
    </div>
    <Table size="small" rowKey="index" dataSource={rows} scroll={{ x: 600 }}
      pagination={{ ...pagination, current: page, onChange: setPage }} locale={{ emptyText: query ? '没有找到匹配内容' : `暂无${label}，点击右上角添加` }}
      columns={[
        { title: examples ? '问题' : '规则标题', key: 'title', width: '35%', ellipsis: true, render: (_: unknown, item: Entry) => <Button type="link" className="knowledge-row-link" onClick={() => open(item.index)}>{item.question || item.title || '历史示例（待整理）'}</Button> },
        { title: examples ? 'SQL 预览' : '规则内容', key: 'content', ellipsis: true, render: (_: unknown, item: Entry) => item.sql || item.content },
        { title: '操作', key: 'actions', width: 130, render: (_: unknown, item: Entry) => <Space size={0}>
          <Button type="link" onClick={() => open(item.index)}>编辑</Button>
          <Popconfirm title={`删除这条${label}？`} onConfirm={async () => { await commit({ [field]: items.filter((_, i) => i !== item.index) }); }} disabled={saving}>
            <Button type="link" danger disabled={saving}>删除</Button>
          </Popconfirm>
        </Space> },
      ]} />
    <Drawer forceRender width={720} title={`${editing === -1 ? '添加' : '编辑'}${label}`} open={editing !== null}
      onClose={() => { if (!saving) setEditing(null); }} maskClosable={!saving} closable={!saving}
      footer={<Space><Button type="primary" loading={saving} onClick={() => form.submit()}>保存{label}</Button><Button disabled={saving} onClick={() => setEditing(null)}>取消</Button></Space>}>
      <Form name={`knowledge-${field}`} form={form} layout="vertical" onFinish={save}>
        {legacy ? <>
          <Alert type="info" showIcon title="这条历史内容尚未识别为问题和 SQL，已完整保留。可以编辑原文，或另建一条标准示例后再删除此条。" style={{ marginBottom: 16 }} />
          <Form.Item name="content" label="历史示例内容" rules={required('示例内容')}><Input.TextArea autoSize={{ minRows: 12, maxRows: 26 }} /></Form.Item>
        </> : examples ? <>
          <Form.Item name="question" label="业务问题" rules={required('业务问题')} extra="粘贴用户提问，例如：上个月每个区域的已完成订单数是多少？"><Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} /></Form.Item>
          <Form.Item name="sql" label="对应 SQL" rules={required('SQL')} extra="粘贴已核对的查询语句。保存示例不会执行 SQL。"><Input.TextArea className="knowledge-sql-input" autoSize={{ minRows: 12, maxRows: 26 }} spellCheck={false} placeholder="SELECT ..." /></Form.Item>
        </> : <>
          <Form.Item name="title" label="规则标题" rules={required('规则标题')} extra="填写短语即可，不用加编号或“【业务规则】”等章节标题。"><Input maxLength={120} placeholder="例如：订单统计范围" /></Form.Item>
          <Form.Item name="content" label="规则内容" rules={required('规则内容')} extra="只填写正文，不用重复标题。序号和章节由系统自动拼接。"><Input.TextArea autoSize={{ minRows: 6, maxRows: 20 }} placeholder="例如：统计订单收入和订单数量时，只统计 order_status = 'completed' 的订单。" /></Form.Item>
        </>}
      </Form>
    </Drawer>
  </>;
};

export const KnowledgeManagement: React.FC<{ knowledge: Knowledge; onSave: (knowledge: Knowledge) => Promise<void> }> = ({ knowledge, onSave }) => {
  const [saving, setSaving] = useState(false);
  const commit: Commit = async (patch) => {
    setSaving(true);
    try { await onSave(patch); message.success('已保存'); return true; }
    catch (error: any) { message.error(error.message || '保存失败，请重试'); return false; }
    finally { setSaving(false); }
  };
  return <Tabs items={[
    { key: 'rules', label: `业务规则（${(knowledge.business_rule_items || []).length}）`, children: <EntryList items={knowledge.business_rule_items || []} field="business_rule_items" label="业务规则" saving={saving} commit={commit} /> },
    { key: 'guards', label: `错误防护（${(knowledge.error_guard_items || []).length}）`, children: <EntryList items={knowledge.error_guard_items || []} field="error_guard_items" label="防护规则" saving={saving} commit={commit} /> },
    { key: 'examples', label: `SQL 示例（${(knowledge.sql_examples || []).length}）`, children: <EntryList items={knowledge.sql_examples || []} field="sql_examples" label="SQL 示例" examples saving={saving} commit={commit} /> },
  ]} />;
};
