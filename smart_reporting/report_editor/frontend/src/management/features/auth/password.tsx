import { useState } from 'react'
import { Alert, Button, Card, Form, Input } from 'antd'
import { useSession } from '../../app/session'
import { request, emptySchema } from '../../api/http'
import { PageHeader } from '../../components/common'
export default function Password() {
  const { state, clear } = useSession(),
    [form] = Form.useForm(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  return (
    <>
      <PageHeader
        title="修改密码"
        description="更新后，全部旧会话将失效，需要重新登录。"
      />
      <Card>
        {error && <Alert type="error" title={error} />}
        <Form
          form={form}
          layout="vertical"
          className="management-narrow-form"
          onFinish={async (values) => {
            setBusy(true)
            setError('')
            try {
              await request('/auth/password', emptySchema, {
                method: 'POST',
                body: values,
                csrf: state.session!.csrfToken,
              })
              clear('密码已更新，请使用新密码登录。')
            } catch (e) {
              setError((e as Error).message)
            } finally {
              form.resetFields()
              setBusy(false)
            }
          }}
        >
          <Form.Item
            name="currentPassword"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              {
                required: true,
                min: 12,
                max: 128,
                message: '请输入 12–128 个字符',
              },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>
            更新密码
          </Button>
        </Form>
      </Card>
    </>
  )
}
