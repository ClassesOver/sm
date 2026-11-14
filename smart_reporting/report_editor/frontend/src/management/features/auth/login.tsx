import React, { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { Navigate, useSearchParams } from 'react-router-dom'
import { ProductIdentity } from '../../components/common'
import { useSession } from '../../app/session'
import { request, emptySchema, advanceSession, ApiError } from '../../api/http'
export function safeReturnTo(value: string | null) {
  if (!value || !value.startsWith('/management/') || value.startsWith('//'))
    return '/management/sources'
  try {
    const u = new URL(value, location.origin)
    if (
      u.origin !== location.origin ||
      !/^\/management\/(sources(?:\/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}(?:\/(?:edit|view))?)?|metrics|statistical-policies|knowledge|report-issues|system-configuration|preferences|account\/password)$/.test(
        u.pathname,
      )
    )
      return '/management/sources'
    return u.pathname + u.search
  } catch {
    return '/management/sources'
  }
}
export default function Login() {
  const { state, load } = useSession(),
    [params] = useSearchParams(),
    [form] = Form.useForm(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [retryAt, setRetryAt] = useState(0),
    [now, setNow] = useState(Date.now())
  React.useEffect(() => {
    if (!retryAt) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [retryAt])
  if (state.status === 'authenticated')
    return (
      <Navigate
        replace
        to={safeReturnTo(params.get('returnTo')).slice('/management'.length)}
      />
    )
  const seconds = Math.max(0, Math.ceil((retryAt - now) / 1000))
  return (
    <main className="management-login">
      <Card className="management-login-card">
        <div className="management-brand">
          <ProductIdentity />
        </div>
        <h1>欢迎登录</h1>
        <Typography.Paragraph type="secondary">
          管理数据源与发布配置，让每次变更有据可查。
        </Typography.Paragraph>
        {(error || state.error) && (
          <Alert
            role="alert"
            type="error"
            showIcon
            title={error || state.error}
            style={{ marginBottom: 24 }}
          />
        )}
        <Form
          form={form}
          layout="vertical"
          initialValues={{ username: 'admin' }}
          onFinish={async (values) => {
            setBusy(true)
            setError('')
            try {
              advanceSession()
              await request('/auth/login', emptySchema, {
                method: 'POST',
                body: values,
              })
              await load()
            } catch (e) {
              setError(e instanceof Error ? e.message : '登录失败')
              if (e instanceof ApiError && e.retryAfter)
                setRetryAt(Date.now() + e.retryAfter * 1000)
            } finally {
              form.setFieldValue('password', '')
              setBusy(false)
            }
          }}
        >
          <Form.Item name="username" label="用户名">
            <Input readOnly autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password autoComplete="current-password" maxLength={128} />
          </Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            block
            loading={busy}
            disabled={seconds > 0}
          >
            {seconds > 0 ? `${seconds} 秒后重试` : '登录'}
          </Button>
        </Form>
        <details>
          <summary>首次使用或忘记密码</summary>
          <p>请联系部署管理员初始化或重置账号。管理员可在项目目录运行：</p>
          <code>
            .venv/bin/python -m smart_reporting.management.cli bootstrap-admin
          </code>
          <p>已有账号使用 reset-admin-password。重置会撤销原有会话。</p>
        </details>
      </Card>
    </main>
  )
}
