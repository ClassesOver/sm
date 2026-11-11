import { flushSync } from 'react-dom'
import React, { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Radio,
  Select,
  Space,
} from 'antd'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import {
  draftSchema,
  detailSchema,
  optionSchema,
  pageSchema,
  type Draft,
} from '../../api/contracts'
import { ApiError, identity, request, scopeQuery } from '../../api/http'
import { useSession } from '../../app/session'
import { PageHeader, AsyncState } from '../../components/common'
import { UnsavedChangesGuard } from '../../components/UnsavedChangesGuard'
import { scopeSuffix, useScope } from '../scopes/context'
import { useSource, type ScopeIdentity } from './queries'
import { mergeDraft } from './conflict'
import { sourceDetailPath } from './paths'

type Values = {
  name: string
  database: string
  profile: string
  metadata: string
}
const publicValues = (d: Draft): Values => ({
  name: d.name,
  database: d.database,
  profile: d.profile_version_id || '',
  metadata: d.metadata_version_id || '',
})
const labels: Record<keyof Values, string> = {
  name: '数据源名称',
  database: '连接数据库',
  profile: '业务口径版本',
  metadata: '数据目录版本',
}
function VersionSelect({
  scope,
  id,
  sourceId,
  kind,
  value,
  onChange,
}: {
  scope: ScopeIdentity
  id?: string
  sourceId?: string
  kind: 'profiles' | 'catalog'
  value?: string
  onChange?: (v: string) => void
}) {
  const path =
    kind === 'profiles'
      ? '/profiles/versions'
      : `/sources/${encodeURIComponent(sourceId || '')}/catalog/versions`
  const query = useInfiniteQuery({
    queryKey: [
      'management',
      'versions',
      scope.database,
      scope.companyId,
      kind,
      sourceId,
    ],
    enabled: kind === 'profiles' || !!sourceId,
    initialPageParam: '',
    queryFn: ({ pageParam, signal }) =>
      request(
        path +
          '?' +
          scopeQuery(scope) +
          (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''),
        pageSchema(optionSchema),
        { signal },
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
  })
  const options =
    query.data?.pages
      .flatMap((p) => p.items)
      .map((v) => ({ value: v.ref, label: v.ref })) || []
  if (value && !options.some((o) => o.value === value))
    options.unshift({ value, label: value + '（当前绑定）' })
  return (
    <>
      <Select
        id={id}
        aria-label={kind === 'profiles' ? '业务口径版本' : '数据目录版本'}
        allowClear
        value={value || undefined}
        onChange={(v) => onChange?.(v || '')}
        loading={query.isFetching}
        options={options}
        placeholder="选择已发布版本"
        notFoundContent={
          query.error
            ? '读取失败'
            : kind === 'catalog' && !sourceId
              ? '先保存数据源后配置目录'
              : '尚无已发布版本'
        }
        popupRender={(node) => (
          <>
            {node}
            {query.hasNextPage && (
              <Button block onClick={() => void query.fetchNextPage()}>
                加载更多版本
              </Button>
            )}
          </>
        )}
      />
      {query.error && (
        <Button size="small" onClick={() => void query.refetch()}>
          重试版本读取
        </Button>
      )}
    </>
  )
}
export default function SourceEditor() {
  const scope = useScope(),
    { sourceId } = useParams(),
    query = useSource(scope, sourceId)
  if (!scope) return <AsyncState empty="请先选择组织。" />
  if (sourceId && !query.data)
    return (
      <AsyncState
        loading={query.isPending}
        error={query.error}
        retry={() => void query.refetch()}
      />
    )
  return (
    <Editor
      key={JSON.stringify([scope, sourceId])}
      scope={scope}
      id={sourceId}
      initial={query.data?.draft}
    />
  )
}
function Editor({
  scope,
  id: initialId,
  initial,
}: {
  scope: ScopeIdentity
  id?: string
  initial?: Draft
}) {
  const [form] = Form.useForm(),
    { state } = useSession(),
    navigate = useNavigate(),
    location = useLocation(),
    returnSearch = location.search || scopeSuffix(scope),
    client = useQueryClient()
  const [id, setId] = useState(initialId),
    [recovery, setRecovery] = useState<Draft | null>(null)
  const [base, setBase] = useState(initial),
    [dirty, setDirty] = useState(false),
    [replace, setReplace] = useState(!id),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [saved, setSaved] = useState(''),
    [uncertain, setUncertain] = useState(false)
  const [conflict, setConflict] = useState<{
      latest: Draft
      values: Values
      fields: (keyof Values)[]
    } | null>(null),
    [choices, setChoices] = useState<
      Partial<Record<keyof Values, 'local' | 'latest'>>
    >({})
  const mounted = useRef(true)
  useEffect(
    () => () => {
      mounted.current = false
      form.setFieldValue('dsn', '')
    },
    [form],
  )
  async function readLatest() {
    return request(
      '/sources/' +
        encodeURIComponent(id || form.getFieldValue('sourceId')) +
        '?' +
        scopeQuery(scope),
      detailSchema,
    )
  }
  async function submit(values: Values & { sourceId?: string; dsn?: string }) {
    if (busy || uncertain) return
    setBusy(true)
    setError('')
    setSaved('')
    try {
      const body = {
        ...identity(scope),
        name: values.name,
        type: 'starrocks',
        database: values.database,
        reportingProfileVersionId: values.profile || null,
        metadataVersionId: values.metadata || null,
        ...(replace ? { dsn: values.dsn } : {}),
        ...(id
          ? { expectedVersion: base!.version }
          : { sourceId: values.sourceId }),
      }
      const result = await request(
        id ? '/sources/' + encodeURIComponent(id) + '/draft' : '/sources',
        draftSchema,
        { method: id ? 'PUT' : 'POST', body, csrf: state.session!.csrfToken },
      )
      if (!mounted.current) {
        void client.invalidateQueries({ queryKey: ['management'] })
        return
      }
      form.setFieldValue('dsn', '')
      setBase(result)
      flushSync(() => setDirty(false))
      setReplace(false)
      setSaved('草稿已保存 v' + result.version + '。发布后才会成为可引用配置。')
      if (!id) {
        navigate(sourceDetailPath(result.source_id) + returnSearch, {
          replace: true,
        })
        return
      }
      if (!initialId && id) {
        navigate(
          '/sources/' + encodeURIComponent(id) + '/edit' + returnSearch,
          { replace: true },
        )
        return
      }
      try {
        await client.invalidateQueries(
          { queryKey: ['management'] },
          { throwOnError: true },
        )
      } catch (refreshError) {
        setError(
          '草稿已保存，关联数据刷新失败：' + (refreshError as Error).message,
        )
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
      if (e instanceof ApiError) {
        form.setFields(
          e.fieldErrors.map((f) => ({
            name:
              (
                {
                  reportingProfileVersionId: 'profile',
                  metadataVersionId: 'metadata',
                } as Record<string, string>
              )[f.field] || f.field,
            errors: [f.message],
          })),
        )
        if (e.status === 409 && !id) {
          form.setFieldValue('dsn', '')
          try {
            setRecovery((await readLatest()).draft)
            setUncertain(true)
          } catch (readError) {
            setError((readError as Error).message)
          }
        }
        if (e.status === 409 && base) {
          form.setFieldValue('dsn', '')
          setReplace(false)
          try {
            const latest = (await readLatest()).draft,
              merged = mergeDraft(
                publicValues(base),
                values,
                publicValues(latest),
              )
            setChoices({})
            setConflict({
              latest,
              values: merged.values,
              fields: merged.conflicts,
            })
          } catch (readError) {
            setError(
              '存在版本冲突；读取最新状态失败：' + (readError as Error).message,
            )
          }
        }
        if (e.status === 0 || (e.code === 'protocol_error' && e.status < 300)) {
          setUncertain(true)
          form.setFieldValue('dsn', '')
        }
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <UnsavedChangesGuard dirty={dirty} />
      <PageHeader
        title={id ? '编辑数据源草稿' : '新建数据源'}
        description="草稿与发布分开生效；连接凭据加密保存且不回显。"
      />
      {saved && (
        <Alert
          role="status"
          type="success"
          title={saved}
          style={{ marginBottom: 16 }}
        />
      )}
      {error && (
        <Alert
          role="alert"
          type="error"
          title={error}
          style={{ marginBottom: 16 }}
        />
      )}
      {uncertain && (
        <Alert
          type="warning"
          title="提交结果待确认，已暂停重复提交"
          description="连接凭据的具体内容无法通过公开字段证明。读取最新版本并核对后，再明确决定是否重新编辑。"
          action={
            <Button
              onClick={async () => {
                try {
                  setRecovery((await readLatest()).draft)
                } catch (e) {
                  if (
                    !id &&
                    e instanceof ApiError &&
                    e.code === 'management_source_not_found'
                  ) {
                    setUncertain(false)
                    setReplace(true)
                    setDirty(true)
                    setError(
                      '当前未找到此标识的数据源。已保留公开输入，请核对标识并重新填写连接后再提交；不会自动重试。',
                    )
                  } else setError((e as Error).message)
                }
              }}
            >
              读取最新状态
            </Button>
          }
        />
      )}
      <Form
        className="management-source-form"
        form={form}
        disabled={busy || uncertain}
        layout="vertical"
        initialValues={
          initial
            ? publicValues(initial)
            : { name: '', database: '', profile: '', metadata: '' }
        }
        onValuesChange={() => setDirty(true)}
        onFinish={submit}
        onFinishFailed={({ errorFields }) =>
          form.scrollToField(errorFields[0]?.name, { focus: true })
        }
      >
        <div className="management-editor-grid">
          <Card title="基本信息">
            <Form.Item
              name="sourceId"
              label="数据源标识"
              hidden={!!id}
              rules={
                id
                  ? []
                  : [
                      { required: true, message: '请输入标识' },
                      {
                        pattern: /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/,
                        message: '使用字母、数字、点、下划线或短横线，最多64位',
                      },
                    ]
              }
            >
              <Input maxLength={64} />
            </Form.Item>
            <Form.Item
              name="name"
              label="数据源名称"
              rules={[{ required: true, message: '请输入名称' }]}
            >
              <Input maxLength={200} />
            </Form.Item>
          </Card>
          <Card title="连接配置">
            {id && (
              <Radio.Group
                value={replace}
                onChange={(e) => {
                  setReplace(e.target.value)
                  form.setFieldValue('dsn', '')
                  setDirty(true)
                }}
                options={[
                  { value: false, label: '保持现有连接' },
                  { value: true, label: '更换连接' },
                ]}
              />
            )}
            <Form.Item
              name="database"
              label="连接数据库"
              rules={[
                { required: true, message: '请输入数据库' },
                {
                  pattern: /^[A-Za-z_][A-Za-z0-9_$]*$/,
                  message: '请输入有效数据库标识',
                },
              ]}
            >
              <Input
                maxLength={128}
                disabled={busy || uncertain || (!!id && !replace)}
              />
            </Form.Item>
            {replace && (
              <Form.Item
                name="dsn"
                label="连接地址（含账号密码）"
                preserve={false}
                rules={[{ required: true, message: '请输入连接地址' }]}
              >
                <Input.Password
                  autoComplete="off"
                  maxLength={4096}
                  placeholder="starrocks://用户名:密码@主机:9030/数据库"
                />
              </Form.Item>
            )}
            <p>连接状态未检测。发布状态不代表连接正常。</p>
          </Card>
          <Card title="发布依赖" className="management-editor-dependencies">
            <p>
              只可选择已有已发布版本。无可选项时请联系运维发布业务口径和同步目录。
            </p>
            <Form.Item name="profile" label="业务口径版本">
              <VersionSelect scope={scope} kind="profiles" />
            </Form.Item>
            <Form.Item name="metadata" label="数据目录版本">
              <VersionSelect scope={scope} sourceId={id} kind="catalog" />
            </Form.Item>
          </Card>
        </div>
        <div className="management-save-bar">
          <span className="management-save-state" role="status">
            {busy
              ? '正在保存…'
              : dirty
                ? '有未保存的修改'
                : id
                  ? '所有修改已保存'
                  : '尚未创建草稿'}
          </span>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              aria-label="保存草稿"
              loading={busy}
              disabled={uncertain}
            >
              保存草稿
            </Button>
            <Button
              onClick={() =>
                navigate(
                  id
                    ? sourceDetailPath(id) + returnSearch
                    : '/sources' + returnSearch,
                )
              }
            >
              取消
            </Button>
          </Space>
        </div>
      </Form>
      <Modal
        open={!!recovery}
        title="核对提交结果"
        onCancel={() => setRecovery(null)}
        footer={
          <Space>
            <Button
              onClick={() => {
                if (!recovery) return
                setId(recovery.source_id)
                setBase(recovery)
                form.setFieldValue('dsn', '')
                setReplace(false)
                setUncertain(false)
                setDirty(true)
                setRecovery(null)
                setError(
                  '已保留本地公开输入，并采用服务器最新版本作为保存基础。请核对后保存；更换连接须重新输入。',
                )
              }}
            >
              保留我的输入继续编辑
            </Button>
            <Button
              type="primary"
              onClick={() => {
                if (!recovery) return
                setId(recovery.source_id)
                setBase(recovery)
                form.setFieldsValue(publicValues(recovery))
                form.setFieldValue('dsn', '')
                setReplace(false)
                setUncertain(false)
                setDirty(false)
                setRecovery(null)
                setError('')
                setSaved('已采用服务器草稿 v' + recovery.version + '。')
              }}
            >
              采用服务器版本
            </Button>
          </Space>
        }
      >
        <p>
          服务器已存在数据源 {recovery?.source_id}，当前草稿 v
          {recovery?.version}。确认后将编辑此数据源。
        </p>
        <p>
          公开字段一致不能证明丢失响应中的连接明文已保存。需要更换连接时，请重新输入；本次不会自动重试写入。
        </p>
        {recovery && (
          <dl>
            {(Object.keys(labels) as (keyof Values)[]).map((field) => (
              <React.Fragment key={field}>
                <dt>{labels[field]}</dt>
                <dd>
                  我的输入：{form.getFieldValue(field) || '未绑定'}；服务器：
                  {publicValues(recovery)[field] || '未绑定'}
                </dd>
              </React.Fragment>
            ))}
          </dl>
        )}
      </Modal>
      <Modal
        open={!!conflict}
        title="草稿已被其他操作更新"
        width={720}
        className="management-conflict-modal"
        okText="采用合并结果继续编辑"
        cancelText="继续查看本地输入"
        okButtonProps={{ disabled: conflict?.fields.some((f) => !choices[f]) }}
        onCancel={() => setConflict(null)}
        onOk={() => {
          if (!conflict) return
          const values = { ...conflict.values },
            latest = publicValues(conflict.latest)
          for (const f of conflict.fields)
            if (choices[f] === 'latest') values[f] = latest[f]
          form.setFieldsValue(values)
          setBase(conflict.latest)
          setDirty(true)
          setConflict(null)
          setError('已合并到最新版本，请核对后再次保存。')
        }}
      >
        <p>
          连接输入已清除。单边修改自动保留，双方修改的字段须明确选择；不会强制覆盖。
        </p>
        {conflict?.fields.map((f) => (
          <div key={f} className="management-conflict-field">
            <strong>{labels[f]}</strong>
            <Radio.Group
              value={choices[f]}
              onChange={(e) =>
                setChoices((v) => ({ ...v, [f]: e.target.value }))
              }
              className="management-conflict-options"
            >
              <Radio value="local">
                <span>我的输入</span>
                <strong>{conflict.values[f] || '未绑定'}</strong>
              </Radio>
              <Radio value="latest">
                <span>服务器最新值</span>
                <strong>{publicValues(conflict.latest)[f] || '未绑定'}</strong>
              </Radio>
            </Radio.Group>
          </div>
        ))}
      </Modal>
    </>
  )
}
