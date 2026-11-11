import React, { useEffect, useRef, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Drawer,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  tableAccessSchema,
  discoverySchema,
  discoveredTablesSchema,
  tableColumnsSchema,
  savedAccessSchema,
  type TableIdentity,
  type DiscoveredTable,
} from '../../api/contracts'
import { ApiError, identity, request, scopeQuery } from '../../api/http'
import { useSession } from '../../app/session'
import { UnsavedChangesGuard } from '../../components/UnsavedChangesGuard'
import { selectPage, tableChanges, tableKey } from './table-selection'
import type { ScopeIdentity } from './queries'

export default function TableAccess({
  scope,
  id,
  onDirty,
}: {
  scope: ScopeIdentity
  id: string
  onDirty: (dirty: boolean) => void
}) {
  const { state } = useSession(),
    client = useQueryClient(),
    { message } = App.useApp()
  const base = '/sources/' + encodeURIComponent(id),
    suffix = '?' + scopeQuery(scope)
  const [selected, setSelected] = useState<TableIdentity[]>([]),
    [version, setVersion] = useState(0)
  const [discovery, setDiscovery] = useState<string | null>(null),
    [dirty, setDirty] = useState(false)
  const [selectedPage, setSelectedPage] = useState(1)
  const [q, setQ] = useState(''),
    [kind, setKind] = useState('all'),
    [offset, setOffset] = useState(0),
    [onlySelected, setOnlySelected] = useState(false)
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [unknown, setUnknown] = useState(false)
  const [warnings, setWarnings] = useState<string[]>([]),
    [column, setColumn] = useState<TableIdentity | null>(null)
  const [recovery, setRecovery] = useState<
    React.ComponentProps<typeof Recovery>['latest'] | null
  >(null)
  useEffect(() => {
    onDirty(dirty || busy || unknown)
    return () => onDirty(false)
  }, [dirty, busy, unknown, onDirty])
  const initialized = useRef(false),
    pending = useRef(false)
  const query = useQuery({
    queryKey: [
      'management',
      'table-access',
      scope.database,
      scope.companyId,
      id,
    ],
    queryFn: ({ signal }) =>
      request(base + '/table-access' + suffix, tableAccessSchema, { signal }),
  })
  useEffect(() => {
    if (query.data && !initialized.current) {
      initialized.current = true
      setSelected(query.data.draftTables)
      setVersion(query.data.draftVersion)
      setDiscovery(query.data.discoveryId)
      setWarnings(query.data.warnings)
    }
  }, [query.data])
  const candidates = useQuery({
    queryKey: [
      'management',
      'discovered-tables',
      scope.database,
      scope.companyId,
      id,
      discovery,
      q,
      kind,
      offset,
      version,
    ],
    enabled: !!discovery,
    queryFn: ({ signal }) =>
      request(
        base +
          '/table-discoveries/' +
          discovery +
          '/tables' +
          suffix +
          '&' +
          new URLSearchParams({ q, kind, offset: String(offset), limit: '25' }),
        discoveredTablesSchema,
        { signal },
      ),
  })
  const known = useRef(new Map<string, DiscoveredTable>())
  useEffect(() => {
    for (const table of [
      ...(candidates.data?.selectedItems || []),
      ...(candidates.data?.items || []),
    ])
      known.current.set(tableKey(table), table)
  }, [candidates.data])
  const columns = useQuery({
    queryKey: [
      'management',
      'table-columns',
      scope.database,
      scope.companyId,
      id,
      discovery,
      column,
    ],
    enabled: !!column && !!discovery,
    queryFn: ({ signal }) =>
      request(
        base +
          '/table-discoveries/' +
          discovery +
          '/columns' +
          suffix +
          '&' +
          new URLSearchParams({
            database: column!.database,
            table: column!.name,
          }),
        tableColumnsSchema,
        { signal },
      ),
  })
  const published = query.data?.publishedTables || [],
    changes = tableChanges(published, selected),
    selectedKeys = new Set(selected.map(tableKey)),
    publishedKeys = new Set(published.map(tableKey))
  const rows = onlySelected
    ? selected
        .map((t) => ({
          ...t,
          type: known.current.get(tableKey(t))?.type || 'unknown',
          description: known.current.get(tableKey(t))?.description || '',
          published: publishedKeys.has(tableKey(t)),
        }))
        .filter(
          (t) =>
            !q ||
            (t.database + '.' + t.name + ' ' + t.description)
              .toLocaleLowerCase()
              .includes(q.toLocaleLowerCase()),
        )
    : candidates.data?.items || []
  const currentPage = Math.min(
    selectedPage,
    Math.max(1, Math.ceil(rows.length / 25)),
  )
  const currentRows = onlySelected
    ? rows.slice((currentPage - 1) * 25, currentPage * 25)
    : rows
  async function refresh() {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    setError('')
    try {
      const result = await request(
        base + '/table-discoveries',
        discoverySchema,
        {
          method: 'POST',
          csrf: state.session!.csrfToken,
          body: { ...identity(scope), expectedDraftVersion: version },
        },
      )
      setDiscovery(result.discoveryId)
      setWarnings(result.warnings)
      setOffset(0)
      void message.success(
        '目录读取成功，共发现 ' +
          result.tableCount +
          ' 个对象；本次未执行业务查询。',
      )
      await query.refetch()
    } catch (e) {
      setError((e as Error).message)
      if (
        e instanceof ApiError &&
        (e.status === 0 || e.code === 'protocol_error')
      )
        setUnknown(true)
    } finally {
      pending.current = false
      setBusy(false)
    }
  }
  async function save() {
    if (pending.current || unknown) return
    pending.current = true
    setBusy(true)
    setError('')
    try {
      const result = await request(base + '/table-access', savedAccessSchema, {
        method: 'PUT',
        csrf: state.session!.csrfToken,
        body: {
          ...identity(scope),
          expectedDraftVersion: version,
          discoveryId: discovery,
          selectedTables: selected,
        },
      })
      setVersion(result.draftVersion)
      setDirty(false)
      setWarnings(result.warnings)
      void message.success(
        '表范围已保存到草稿 v' +
          result.draftVersion +
          '，发布后仅对新报告生效。',
      )
      await client.invalidateQueries({ queryKey: ['management'] })
    } catch (e) {
      setError((e as Error).message)
      if (
        e instanceof ApiError &&
        (e.status === 0 || e.code === 'protocol_error')
      )
        setUnknown(true)
    } finally {
      pending.current = false
      setBusy(false)
    }
  }
  function update(page: TableIdentity[], checked: boolean) {
    setSelected((previous) => selectPage(previous, page, checked))
    setDirty(true)
  }
  return (
    <>
      <UnsavedChangesGuard dirty={dirty} />
      <Card
        className="management-access-card"
        title="报告可访问的表和视图"
        extra={
          <Button
            loading={busy}
            disabled={!version || unknown}
            onClick={() => void refresh()}
          >
            刷新数据库目录
          </Button>
        }
      >
        <p>
          范围同时控制报告 AI 可见目录与实际 SQL
          查询。新发现对象默认不暴露，字段仅供结构预览。最多选择 200 张表。
        </p>
        {query.isPending && <p role="status">正在读取表范围…</p>}
        {query.error && (
          <Alert
            type="error"
            title={query.error.message}
            action={
              <Button onClick={() => void query.refetch()}>重试读取</Button>
            }
          />
        )}
        {query.data?.needsDiscovery && (
          <Alert
            type="warning"
            title="连接已更换，请重新发现数据库目录，并明确保存新范围后再发布。"
          />
        )}
        {warnings.map((w) => (
          <Alert type="warning" key={w} title={w} />
        ))}
        {error && (
          <Alert
            role="alert"
            type="error"
            title={error}
            action={
              <Button
                disabled={busy}
                onClick={async () => {
                  try {
                    setRecovery(
                      await request(
                        base + '/table-access' + suffix,
                        tableAccessSchema,
                      ),
                    )
                  } catch (e) {
                    setError((e as Error).message)
                  }
                }}
              >
                读取最新范围并核对
              </Button>
            }
          />
        )}
        {unknown && (
          <Alert
            type="warning"
            title="提交结果待确认；请读取最新版本和实际选择，核对后再决定，不会自动重试。"
          />
        )}
        {query.data?.discoveredAt && (
          <p className="management-secondary">
            目录发现时间：{new Date(query.data.discoveredAt).toLocaleString()} ·
            目录读取成功不代表业务查询健康
          </p>
        )}
        {!discovery && (
          <Alert
            type="info"
            title="保存连接后，点击“刷新数据库目录”发现当前数据库的表与视图。"
          />
        )}
        {discovery && (
          <>
            <div className="management-toolbar" style={{ marginTop: 16 }}>
              <Input.Search
                aria-label="搜索表"
                placeholder="搜索表名或说明"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value)
                  setOffset(0)
                  setSelectedPage(1)
                }}
                allowClear
              />
              <Select
                aria-label="对象类型"
                value={kind}
                disabled={onlySelected}
                onChange={(v) => {
                  setKind(v)
                  setOffset(0)
                }}
                options={[
                  { value: 'all', label: '表和视图' },
                  { value: 'table', label: '仅表' },
                  { value: 'view', label: '仅视图' },
                ]}
              />
              <Checkbox
                checked={onlySelected}
                onChange={(e) => {
                  setOnlySelected(e.target.checked)
                  setOffset(0)
                  setSelectedPage(1)
                }}
              >
                只看已选
              </Checkbox>
            </div>
            {candidates.error && (
              <Alert
                type="error"
                title={candidates.error.message}
                action={
                  <Button onClick={() => void candidates.refetch()}>
                    重试读取目录
                  </Button>
                }
              />
            )}
            {!!candidates.data?.missingTables.length && (
              <Alert
                type="warning"
                title="以下已选对象已从数据库消失，选择已保留。请明确取消这些对象后保存。"
                description={candidates.data.missingTables
                  .map((t) => t.database + '.' + t.name)
                  .join('、')}
              />
            )}
            <Space wrap className="management-selection-bar">
              <Button
                disabled={
                  busy || unknown || candidates.isFetching || !!candidates.error
                }
                onClick={() => update(currentRows, true)}
              >
                选择本页
              </Button>
              <Button
                disabled={
                  busy || unknown || candidates.isFetching || !!candidates.error
                }
                onClick={() => update(currentRows, false)}
              >
                取消选择本页
              </Button>
              <span role="status">
                已选 {selected.length} / 200 · 新增 {changes.added.length} ·
                移除 {changes.removed.length}
              </span>
            </Space>
            <Table
              size="small"
              rowKey={tableKey}
              loading={candidates.isFetching}
              pagination={
                onlySelected
                  ? {
                      pageSize: 25,
                      showSizeChanger: false,
                      current: currentPage,
                      onChange: setSelectedPage,
                    }
                  : false
              }
              dataSource={rows}
              scroll={{ x: 660, y: 420 }}
              rowSelection={{
                hideSelectAll: true,
                selectedRowKeys: selected.map(tableKey),
                preserveSelectedRowKeys: true,
                onSelect: (record, checked) => update([record], checked),
                onSelectAll: (checked, _, changed) => update(changed, checked),
                getCheckboxProps: (t) => ({
                  disabled: busy || unknown || candidates.isFetching,
                  'aria-label': '选择 ' + t.database + '.' + t.name,
                }),
              }}
              columns={[
                {
                  title: '表名',
                  render: (_, t) => (
                    <Button type="link" onClick={() => setColumn(t)}>
                      {t.database}.{t.name}
                    </Button>
                  ),
                },
                {
                  title: '类型',
                  render: (_, t) =>
                    t.type === 'view'
                      ? '视图'
                      : t.type === 'table'
                        ? '表'
                        : '待核对',
                },
                {
                  title: '说明',
                  dataIndex: 'description',
                  render: (v) => v || '未登记业务说明',
                },
                {
                  title: '范围状态',
                  render: (_, t) => (
                    <Space>
                      {selectedKeys.has(tableKey(t)) && (
                        <Tag color="blue">已选</Tag>
                      )}
                      {t.published && <Tag>已发布</Tag>}
                    </Space>
                  ),
                },
              ]}
            />
            {!onlySelected && (
              <div className="management-pagination">
                <span>共 {candidates.data?.total ?? '—'} 个匹配对象</span>
                <Space>
                  <Button
                    disabled={offset === 0 || candidates.isFetching}
                    onClick={() => setOffset(Math.max(0, offset - 25))}
                  >
                    上一页
                  </Button>
                  <Button
                    disabled={
                      candidates.data?.nextOffset == null ||
                      candidates.isFetching
                    }
                    onClick={() => setOffset(candidates.data!.nextOffset!)}
                  >
                    下一页
                  </Button>
                </Space>
              </div>
            )}
          </>
        )}
        <div className="management-save-bar">
          <span>
            {dirty
              ? '有未保存的表范围变更，请先保存后发布'
              : '表范围与草稿一致'}
            {selected.length === 0 &&
              ' · 至少选择一张有效表才可保存，空选择可继续编辑。'}
          </span>
          <Button
            type="primary"
            disabled={
              !dirty ||
              !discovery ||
              selected.length === 0 ||
              selected.length > 200 ||
              unknown ||
              !!candidates.error
            }
            loading={busy}
            onClick={() => void save()}
          >
            保存表范围
          </Button>
        </div>
      </Card>
      <Drawer
        title={
          column
            ? column.database + '.' + column.name + ' · 字段结构'
            : '字段结构'
        }
        open={!!column}
        onClose={() => setColumn(null)}
        size={640}
      >
        <p>字段仅供结构预览；表级范围决定访问权限。</p>
        {columns.error && <Alert type="error" title={columns.error.message} />}
        <div
          tabIndex={0}
          role="region"
          aria-label="字段结构，可横向滚动"
          style={{ overflowX: 'auto' }}
        >
          <Table
            size="small"
            style={{ minWidth: 440 }}
            loading={columns.isFetching}
            dataSource={columns.data?.columns || []}
            rowKey="name"
            pagination={false}
            columns={[
              { title: '字段名', dataIndex: 'name' },
              { title: '类型', dataIndex: 'dataType' },
              { title: '可空', render: (_, c) => (c.nullable ? '是' : '否') },
              { title: '说明', dataIndex: 'description' },
            ]}
          />
        </div>
      </Drawer>
      {recovery && (
        <Recovery
          latest={recovery}
          selected={selected}
          onCancel={() => setRecovery(null)}
          onUse={(keep) => {
            if (!keep) {
              setSelected(recovery.draftTables)
              setDirty(false)
            } else setDirty(true)
            setVersion(recovery.draftVersion)
            setDiscovery(recovery.discoveryId)
            setOffset(0)
            setWarnings(recovery.warnings)
            setUnknown(false)
            setRecovery(null)
            setError('')
            void client.invalidateQueries({ queryKey: ['management'] })
          }}
        />
      )}
    </>
  )
}
function Recovery({
  latest,
  selected,
  onCancel,
  onUse,
}: {
  latest: {
    draftVersion: number
    draftTables: TableIdentity[]
    discoveryId: string | null
    warnings: string[]
  }
  selected: TableIdentity[]
  onCancel: () => void
  onUse: (keep: boolean) => void
}) {
  return (
    <Modal
      open
      title="核对服务器范围与本地选择"
      onCancel={onCancel}
      footer={
        <Space wrap>
          <Button onClick={() => onUse(true)}>保留本地选择继续核对</Button>
          <Button type="primary" onClick={() => onUse(false)}>
            采用服务器范围
          </Button>
        </Space>
      }
    >
      <p>
        服务器草稿 v{latest.draftVersion}
        。采用新版本后仍需明确点击保存，不会自动重试。
      </p>
      <div className="management-range-comparison">
        <div>
          <h3>本地选择（{selected.length}）</h3>
          {selected.map((t) => (
            <div key={tableKey(t)}>
              {t.database}.{t.name}
            </div>
          ))}
        </div>
        <div>
          <h3>服务器范围（{latest.draftTables.length}）</h3>
          {latest.draftTables.map((t) => (
            <div key={tableKey(t)}>
              {t.database}.{t.name}
            </div>
          ))}
        </div>
      </div>
    </Modal>
  )
}
