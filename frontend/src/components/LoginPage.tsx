import React, { useState } from 'react';
import { Card, Form, Input, Button, Typography, Alert } from 'antd';
import { UserOutlined, LockOutlined, DatabaseOutlined } from '@ant-design/icons';
import { login, register, saveToken } from '../services/chatbiApi';

const { Title, Text } = Typography;

interface LoginPageProps {
  onLogin: () => void;
}

interface LoginFormValues {
  username: string;
  password: string;
  confirmPassword?: string;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLogin }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [mode, setMode] = useState<'login' | 'register'>('login');

  const handleFinish = async (values: LoginFormValues) => {
    setLoading(true);
    setError('');
    try {
      if (mode === 'register') {
        const result = await register(values.username, values.password);
        setMode('login');
        setSuccess(result.message);
      } else {
        const result = await login(values.username, values.password);
        saveToken(result.token);
        onLogin();
      }
    } catch (err: any) {
      setError(err.message || (mode === 'login' ? '登录失败' : '注册失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-intro">
        <div className="auth-intro-brand"><span><DatabaseOutlined /></span> ChatBI</div>
        <div className="auth-intro-copy">
          <span className="auth-intro-kicker">DATA WORKSPACE</span>
          <h1>让每个业务问题<br />都有数据依据。</h1>
          <p>在同一个工作区完成提问、分析和结果回顾。</p>
        </div>
        <div className="auth-intro-foot">面向授权用户的数据分析空间</div>
      </div>
      <div className="auth-form-side">
      <Card className="auth-card" variant="borderless">
        <div className="auth-form-heading">
          <span className="auth-form-kicker">WELCOME TO CHATBI</span>
          <Title level={3}>{mode === 'login' ? '欢迎回来' : '创建账号'}</Title>
          <Text type="secondary">
            {mode === 'login' ? '登录后继续使用数据工作台' : '注册后由管理员授予访问权限'}
          </Text>
        </div>

        {error && (
          <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />
        )}
        {success && (
          <Alert type="success" message={success} showIcon style={{ marginBottom: 16 }} />
        )}

        <Form<LoginFormValues> key={mode} onFinish={handleFinish} size="large">
          <Form.Item
            name="username"
            rules={mode === 'register'
              ? [{ required: true, pattern: /^[A-Za-z0-9_]{3,32}$/, message: '用户名须为 3～32 位字母、数字或下划线' }]
              : [{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={mode === 'register'
              ? [{ required: true, min: 8, max: 128, message: '密码长度须为 8～128 位' }]
              : [{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </Form.Item>
          {mode === 'register' && (
            <Form.Item
              name="confirmPassword"
              dependencies={['password']}
              rules={[
                { required: true, message: '请再次输入密码' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    return !value || getFieldValue('password') === value
                      ? Promise.resolve()
                      : Promise.reject(new Error('两次输入的密码不一致'));
                  },
                }),
              ]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="确认密码"
                autoComplete="new-password"
              />
            </Form.Item>
          )}
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              {mode === 'login' ? '登录' : '注册'}
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center' }}>
          <Button
            type="link"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login');
              setError('');
              setSuccess('');
            }}
          >
            {mode === 'login' ? '没有账号？注册' : '已有账号？登录'}
          </Button>
        </div>
      </Card>
      <div className="auth-form-foot">© ChatBI · 数据工作台</div>
      </div>
    </div>
  );
};
