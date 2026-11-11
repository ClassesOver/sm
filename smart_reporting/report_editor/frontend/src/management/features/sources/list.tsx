import { sourceDetailPath } from './paths'
import React, { useEffect, useState } from 'react'
import { Alert, Button, Card, Grid, Input, Select, Space, Table } from 'antd'
import PlusOutlined from '@ant-design/icons/PlusOutlined'
import ReloadOutlined from '@ant-design/icons/ReloadOutlined'
import DatabaseOutlined from '@ant-design/icons/DatabaseOutlined'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { useScope } from '../scopes/context'
import { useSources } from './queries'
import { PageHeader, AsyncState, StatusTag } from '../../components/common'
export default function Sources() {
  const screens = Grid.useBreakpoint()
  const navigate = useNavigate(),
    scope = useScope(),
    [params, setParams] = useSearchParams(),
    q = params.get('q') || '',
    status = params.get('status') || 'all',
    [input, setInput] = useState(q),
    query = useSources(scope, q, status)
  useEffect(() => setInput(q), [q])
  useEffect(() => {
    const timer = setTimeout(() => {
      if (input !== q)
        setParams((p) => {
          p.set('q', input)
          return p
        })
    }, 300)
    return () => clearTimeout(timer)
  }, [input, q, setParams])
  const items = query.data?.pages.flatMap((p) => p.items) || []
  return (
    <>
      <PageHeader
        title="数据源"
        description="连接业务数据，管理报告可访问的表与发布版本。"
        action={
          scope && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => navigate('/sources/new?' + params.toString())}
            >
              新建数据源
            </Button>
          )
        }
      />
      {!scope ? (
        <Card>
          <AsyncState empty="请在顶部选择组织，或先登记组织。" />
          <Link to="/organizations">前往组织管理</Link>
        </Card>
      ) : (
        <Card className="management-source-card">
          <div className="management-toolbar">
            <Input.Search
              aria-label="搜索数据源"
              placeholder="搜索名称或标识"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onSearch={(value) =>
                setParams((p) => {
                  p.set('q', value)
                  return p
                })
              }
              allowClear
            />
            <Select
              aria-label="发布状态"
              value={status}
              onChange={(value) =>
                setParams((p) => {
                  p.set('status', value)
                  return p
                })
              }
              options={[
                { value: 'all', label: '全部状态' },
                { value: 'unpublished', label: '未发布' },
                { value: 'published', label: '已发布' },
                { value: 'changed', label: '有待发布变更' },
              ]}
            />
            <Button
              className="management-toolbar-refresh"
              icon={<ReloadOutlined />}
              loading={query.isFetching && !query.isFetchingNextPage}
              onClick={() => void query.refetch()}
            >
              刷新
            </Button>
          </div>
          {query.error && query.data && (
            <Alert
              type="warning"
              title={'刷新失败，当前显示上次读取的数据：' + query.error.message}
              action={
                <Button onClick={() => void query.refetch()}>重试</Button>
              }
            />
          )}
          <AsyncState
            loading={query.isPending}
            error={!query.data ? query.error : undefined}
            retry={() => void query.refetch()}
          >
            <Table
              rowKey="source_id"
              pagination={false}
              dataSource={items}
              scroll={{ x: 940, y: 'max(260px, calc(100vh - 430px))' }}
              size="middle"
              locale={{
                emptyText:
                  q || status !== 'all'
                    ? '没有匹配的数据源'
                    : '当前组织暂无数据源',
              }}
              columns={[
                {
                  title: '数据源',
                  width: 250,
                  dataIndex: 'name',
                  render: (name, r) => (
                    <div className="management-source-identity">
                      <span
                        className="management-source-icon"
                        aria-hidden="true"
                      >
                        <DatabaseOutlined />
                      </span>
                      <div>
                        <Link
                          to={
                            sourceDetailPath(r.source_id) +
                            '?' +
                            params.toString()
                          }
                        >
                          {name}
                        </Link>
                        <div className="management-secondary management-code">
                          {r.source_id}
                        </div>
                      </div>
                    </div>
                  ),
                },
                {
                  title: '类型 / 数据库',
                  width: 150,
                  render: (_, r) => (
                    <>
                      StarRocks
                      <div className="management-secondary">{r.database}</div>
                    </>
                  ),
                },
                {
                  title: '发布状态',
                  width: 160,
                  render: (_, r) => (
                    <StatusTag
                      published={r.publishedRevision}
                      changed={r.hasUnpublishedChanges}
                    />
                  ),
                },
                {
                  title: '草稿 / 发布版本',
                  width: 150,
                  render: (_, r) => (
                    <>
                      <div>v{r.version}</div>
                      <div className="management-secondary">
                        {r.publishedRevision
                          ? '发布 r' + r.publishedRevision
                          : '尚未发布'}
                      </div>
                    </>
                  ),
                },
                {
                  title: '已发布表',
                  width: 100,
                  align: 'right',
                  render: (_, r) => (
                    <span className="management-table-count">
                      {r.publishedTableCount ?? 0}
                    </span>
                  ),
                },
                {
                  title: '操作',
                  width: 180,
                  fixed: screens.lg ? 'right' : undefined,
                  render: (_, r) => (
                    <Space size={12} className="management-row-actions">
                      <Link
                        to={
                          sourceDetailPath(r.source_id) +
                          '?' +
                          params.toString()
                        }
                      >
                        详情
                      </Link>
                      <Link
                        to={
                          '/sources/' +
                          encodeURIComponent(r.source_id) +
                          '/edit?' +
                          params.toString()
                        }
                      >
                        编辑
                      </Link>
                      <Link
                        to={
                          sourceDetailPath(r.source_id) +
                          '?' +
                          new URLSearchParams({
                            ...Object.fromEntries(params),
                            tab: 'tables',
                          }).toString()
                        }
                      >
                        管理表
                      </Link>
                    </Space>
                  ),
                },
              ]}
            />
            <div className="management-pagination">
              <span>已加载 {items.length} 条</span>
              {query.hasNextPage && (
                <Button
                  loading={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}
                >
                  加载更多
                </Button>
              )}
            </div>
          </AsyncState>
        </Card>
      )}
    </>
  )
}
