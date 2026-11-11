import React, { lazy, Suspense, useState } from 'react'
import { Alert, Button, Card, Descriptions, Skeleton, Space, Tabs } from 'antd'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useScope } from '../scopes/context'
import { useSource } from './queries'
import { PageHeader, AsyncState, StatusTag } from '../../components/common'
import { Release } from './release'
const TableAccess = lazy(() => import('./table-access'))
export default function SourceDetail() {
  const navigate = useNavigate(),
    { sourceId } = useParams(),
    scope = useScope(),
    query = useSource(scope, sourceId)
  const [params, setParams] = useSearchParams(),
    [open, setOpen] = useState(false)
  const [tableDirty, setTableDirty] = useState(false)
  const tab = ['overview', 'tables', 'published'].includes(
    params.get('tab') || '',
  )
    ? params.get('tab')!
    : 'overview'
  if (!scope) return <AsyncState empty="请选择组织后查看数据源。" />
  return (
    <>
      <PageHeader
        title={query.data?.draft.name || '数据源详情'}
        description={sourceId}
        action={
          <Space wrap>
            <Button
              onClick={() => {
                const back = new URLSearchParams(params)
                back.delete('tab')
                navigate('/sources?' + back)
              }}
            >
              返回列表
            </Button>
            <Button
              onClick={() =>
                navigate(
                  '/sources/' +
                    encodeURIComponent(sourceId!) +
                    '/edit?' +
                    params,
                )
              }
            >
              编辑草稿
            </Button>
            <Button
              type="primary"
              disabled={!query.data || tableDirty}
              onClick={() => setOpen(true)}
            >
              发布
            </Button>
          </Space>
        }
      />
      {query.error && query.data && (
        <Alert
          type="warning"
          title={'刷新失败，当前显示上次读取的详情：' + query.error.message}
          action={<Button onClick={() => void query.refetch()}>重试</Button>}
        />
      )}
      <AsyncState
        loading={query.isPending}
        error={!query.data ? query.error : undefined}
        retry={() => void query.refetch()}
      >
        {query.data && (
          <>
            <Tabs
              className="management-detail-tabs"
              activeKey={tab}
              onChange={(key) =>
                setParams((p) => {
                  p.set('tab', key)
                  return p
                })
              }
              destroyOnHidden
              items={[
                {
                  key: 'overview',
                  label: '概览',
                  children: (
                    <Card title="配置概览" className="management-overview-card">
                      <Alert
                        type={
                          query.data.hasUnpublishedChanges ? 'warning' : 'info'
                        }
                        title={
                          query.data.published
                            ? '当前生效版本 v' +
                              query.data.published.revision +
                              (query.data.hasUnpublishedChanges
                                ? ' · 有待发布变更'
                                : ' · 草稿与发布一致')
                            : '尚未发布，配置仅保存在草稿'
                        }
                        style={{ marginBottom: 16 }}
                      />
                      <Descriptions
                        bordered
                        size="small"
                        column={{ xs: 1, sm: 2 }}
                        items={[
                          {
                            key: 'status',
                            label: '发布状态',
                            children: (
                              <StatusTag
                                published={
                                  query.data.published?.revision || null
                                }
                                changed={query.data.hasUnpublishedChanges}
                              />
                            ),
                          },
                          {
                            key: 'draft',
                            label: '当前草稿',
                            children: 'v' + query.data.draft.version,
                          },
                          {
                            key: 'database',
                            label: '连接数据库',
                            children: query.data.draft.database,
                          },
                          {
                            key: 'metadata',
                            label: '数据目录',
                            children:
                              query.data.draft.metadata_version_id || '未绑定',
                          },
                          {
                            key: 'connection',
                            label: '连接状态',
                            children: '未检测',
                          },
                        ]}
                      />
                      <details>
                        <summary>技术详情</summary>
                        <p>草稿内容标识：{query.data.draft.content_hash}</p>
                        {query.data.published && (
                          <p>
                            发布内容标识：{query.data.published.contentHash}
                          </p>
                        )}
                      </details>
                    </Card>
                  ),
                },
                {
                  key: 'tables',
                  label: '表访问范围',
                  children: (
                    <Suspense fallback={<Skeleton active />}>
                      <TableAccess
                        key={
                          scope.database +
                          '/' +
                          scope.companyId +
                          '/' +
                          sourceId
                        }
                        scope={scope}
                        id={sourceId!}
                        onDirty={setTableDirty}
                      />
                    </Suspense>
                  ),
                },
                {
                  key: 'published',
                  label: '当前发布',
                  children: (
                    <Card title="当前已发布版本">
                      {query.data.published ? (
                        <Descriptions
                          column={{ xs: 1, sm: 2 }}
                          items={[
                            {
                              key: 'revision',
                              label: '生效版本',
                              children: 'v' + query.data.published.revision,
                            },
                            {
                              key: 'date',
                              label: '发布时间',
                              children: new Date(
                                query.data.published.publishedAt,
                              ).toLocaleString(),
                            },
                            {
                              key: 'name',
                              label: '名称',
                              children: query.data.published.name,
                            },
                            {
                              key: 'db',
                              label: '数据库',
                              children: query.data.published.database,
                            },
                            {
                              key: 'catalog',
                              label: '目录版本',
                              children: query.data.published.metadataVersionId,
                            },
                          ]}
                        />
                      ) : (
                        <p>尚未发布；草稿不会作为已发布配置生效。</p>
                      )}
                      <p>
                        发布仅影响新报告，运行中与恢复执行的报告继续使用已冻结的版本。
                      </p>
                    </Card>
                  ),
                },
              ]}
            />
            <Release
              scope={scope}
              id={sourceId!}
              detail={query.data}
              open={open}
              onClose={() => setOpen(false)}
            />
          </>
        )}
      </AsyncState>
    </>
  )
}
