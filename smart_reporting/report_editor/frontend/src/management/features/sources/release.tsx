import React from 'react'
import {
  Alert,
  App,
  Button,
  Modal,
  Space,
  Table,
  Typography,
} from 'antd'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  checkSchema,
  publishedSchema,
  detailSchema,
  type Detail,
} from '../../api/contracts'
import { request, identity, scopeQuery, ApiError } from '../../api/http'
import { useSession } from '../../app/session'
import type { ScopeIdentity } from './queries'
export function Release({
  scope,
  id,
  detail,
  open,
  onClose,
}: {
  scope: ScopeIdentity
  id: string
  detail: Detail
  open: boolean
  onClose: () => void
}) {
  const [unknown, setUnknown] = React.useState(false),
    [verified, setVerified] = React.useState('')
  const { state } = useSession(),
    client = useQueryClient(),
    { message } = App.useApp(),
    query = useQuery({
      queryKey: [
        'management',
        'release-check',
        scope.database,
        scope.companyId,
        id,
        detail.draft.version,
      ],
      enabled: open,
      queryFn: ({ signal }) =>
        request(
          '/sources/' +
            encodeURIComponent(id) +
            '/release-check?' +
            scopeQuery(scope) +
            '&expectedVersion=' +
            detail.draft.version,
          checkSchema,
          { signal },
        ),
    }),
    publish = useMutation({
      mutationFn: () =>
        request(
          '/sources/' + encodeURIComponent(id) + '/publish',
          publishedSchema,
          {
            method: 'POST',
            body: {
              ...identity(scope),
              expectedVersion: query.data!.expectedVersion,
            },
            csrf: state.session!.csrfToken,
          },
        ),
      onError: (e) => {
        if (
          e instanceof ApiError &&
          (e.status === 0 || (e.code === 'protocol_error' && e.status < 300))
        )
          setUnknown(true)
      },
      onSuccess: async (result) => {
        void message.success(
          '已发布 v' +
            result.revision +
            ' · ' +
            new Date(result.publishedAt).toLocaleString(),
        )
        onClose()
        await client.invalidateQueries({ queryKey: ['management'] })
      },
    })
  React.useEffect(() => {
    setUnknown(false)
    setVerified('')
    publish.reset()
  }, [id, scope.database, scope.companyId, detail.draft.version])
  return (
    <Modal
      open={open}
      title="确认发布数据源"
      okText="确认发布"
      cancelText="取消"
      confirmLoading={publish.isPending}
      okButtonProps={{
        disabled: unknown || !query.data?.canPublish || query.isFetching,
      }}
      onCancel={onClose}
      onOk={() => {
        if (!publish.isPending && !unknown) publish.mutate()
      }}
    >
      <p>
        机构：{scope.database} / {scope.companyId}
      </p>
      <p>
        数据源：{detail.draft.name}（{id}）
      </p>
      {query.isPending ? (
        <p>正在核对发布条件…</p>
      ) : query.error ? (
        <Alert
          type="error"
          title={query.error.message}
          action={
            <Button onClick={() => void query.refetch()}>重新检查</Button>
          }
        />
      ) : (
        query.data && (
          <>
            <p>
              当前发布版本：
              {query.data.currentPublishedRevision
                ? 'v' + query.data.currentPublishedRevision
                : '未发布'}
            </p>
            {query.data.issues.map((i) => (
              <Alert key={i.code} type="warning" title={i.message} />
            ))}
            {query.data.warnings.map((w) => (
              <Alert type="warning" key={w} title={w} />
            ))}
            {!query.data.hasUnpublishedChanges && (
              <Alert type="info" title="当前草稿已发布，无需重复发布。" />
            )}
            {query.data.changedFields.length > 0 && (
              <Table
                size="small"
                rowKey="field"
                pagination={false}
                dataSource={query.data.changedFields}
                columns={[
                  {
                    title: '配置字段',
                    dataIndex: 'field',
                    render: (field: string) =>
                      ({
                        name: '数据源名称',
                        type: '数据库类型',
                        database: '连接数据库',
                        metadataVersionId: '目录版本',
                      })[field] || field,
                  },
                  { title: '之前', render: (_, r) => String(r.before ?? '—') },
                  { title: '发布后', render: (_, r) => String(r.after ?? '—') },
                ]}
              />
            )}
            {query.data.tableAccessChanges && (
              <div style={{ marginTop: 16 }}>
                <h3>表访问范围</h3>
                <p>
                  当前 {query.data.tableAccessChanges.beforeCount} 张 → 发布后{' '}
                  {query.data.tableAccessChanges.afterCount} 张
                </p>
                <p>
                  新增：{query.data.tableAccessChanges.added.join('、') || '无'}
                </p>
                <p>
                  移除：
                  {query.data.tableAccessChanges.removed.join('、') || '无'}
                </p>
                <Alert
                  type="info"
                  title="仅影响新报告，运行中及恢复执行的报告继续使用冻结版本。"
                />
              </div>
            )}
            {query.data.connectionChanged && (
              <p>连接配置已更换，凭据不会显示。</p>
            )}
          </>
        )
      )}
      {publish.error && (
        <Alert
          role="alert"
          type="error"
          title={publish.error.message}
          action={
            <Button
              onClick={async () => {
                try {
                  const latest = await request(
                    '/sources/' +
                      encodeURIComponent(id) +
                      '?' +
                      scopeQuery(scope),
                    detailSchema,
                  )
                  if (
                    latest.published?.contentHash === detail.draft.content_hash
                  ) {
                    setVerified(
                      '已核实当前发布版本 v' + latest.published.revision,
                    )
                    setUnknown(true)
                  } else {
                    setVerified('当前配置尚未发布，请重新核对发布条件。')
                    setUnknown(false)
                  }
                  await client.invalidateQueries({ queryKey: ['management'] })
                } catch (e) {
                  setVerified('读取失败：' + (e as Error).message)
                }
              }}
            >
              读取最新状态
            </Button>
          }
        />
      )}
      {verified && <Alert role="status" type="info" title={verified} />}
      <Typography.Paragraph type="secondary">
        发布影响后续按配置模式选取的运行；已开始的报告保留冻结配置。连接状态未经检测。
      </Typography.Paragraph>
    </Modal>
  )
}
