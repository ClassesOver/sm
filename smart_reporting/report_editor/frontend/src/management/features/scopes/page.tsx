import React, { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Typography,
} from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { scopeSchema } from '../../api/contracts'
import { request } from '../../api/http'
import { keys } from '../../api/query-keys'
import { PageHeader, AsyncState } from '../../components/common'
import { useSession } from '../../app/session'

import { useScopes } from './queries'
export default function Organizations() {
  const query = useScopes(),
    client = useQueryClient(),
    navigate = useNavigate(),
    { state } = useSession(),
    [open, setOpen] = useState(false),
    [form] = Form.useForm()
  const save = useMutation({
    mutationFn: (body: unknown) =>
      request('/scopes', scopeSchema, {
        method: 'POST',
        body,
        csrf: state.session!.csrfToken,
      }),
    onSuccess: () => {
      setOpen(false)
      form.resetFields()
      void client.invalidateQueries({ queryKey: keys.scopes })
    },
  })
  return (
    <>
      <PageHeader
        title="组织"
        description="登记机构并选择数据源管理范围。"
        action={
          <Button type="primary" onClick={() => setOpen(true)}>
            登记组织
          </Button>
        }
      />
      <Card>
        <AsyncState
          loading={query.isPending}
          error={query.error}
          retry={() => void query.refetch()}
        >
          <Table
            rowKey="id"
            pagination={false}
            dataSource={query.data?.pages.flatMap((p) => p.items)}
            columns={[
              { title: '组织名称', dataIndex: 'name' },
              { title: '数据库标识', dataIndex: 'database' },
              { title: '机构标识', dataIndex: 'companyId' },
              {
                title: '操作',
                render: (_, r) => (
                  <Button
                    type="link"
                    onClick={() =>
                      navigate(
                        '/sources?' +
                          new URLSearchParams({
                            database: r.database,
                            companyId: r.companyId,
                          }),
                      )
                    }
                  >
                    管理数据源
                  </Button>
                ),
              },
            ]}
          />
          {query.hasNextPage && (
            <Button
              loading={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              加载更多
            </Button>
          )}
        </AsyncState>
      </Card>
      <Modal
        title="登记组织"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={save.isPending}
        okText="保存组织"
        cancelText="取消"
      >
        {save.error && <Alert type="error" title={save.error.message} />}
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => save.mutate(values)}
        >
          {[
            ['name', '组织名称'],
            ['database', '组织数据库标识'],
            ['companyId', '机构标识'],
          ].map(([name, label]) => (
            <Form.Item
              key={name}
              name={name}
              label={label}
              rules={[
                {
                  required: true,
                  max: name === 'name' ? 200 : 128,
                  message: '请填写有效值',
                },
              ]}
            >
              <Input />
            </Form.Item>
          ))}
        </Form>
      </Modal>
    </>
  )
}
