import React from 'react'
import { Alert, Button, Empty, Skeleton, Tag } from 'antd'
export function ProductIdentity() {
  return (
    <div className="management-identity">
      <span className="management-product-mark" aria-hidden="true">
        R
      </span>
      <div className="management-identity-text">
        <strong>智能报告</strong>
        <span>管理工作台</span>
      </div>
    </div>
  )
}
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="management-page-header">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  )
}
export function AsyncState({
  loading,
  error,
  retry,
  empty,
  children,
}: {
  loading?: boolean
  error?: unknown
  retry?: () => void
  empty?: string
  children?: React.ReactNode
}) {
  if (loading) return <div className="management-async-state" role="status" aria-busy="true"><p>正在读取…</p><Skeleton active aria-hidden="true" /></div>
  if (error)
    return (
      <Alert
        className="management-async-state"
        type="error"
        showIcon
        title={error instanceof Error ? error.message : '读取失败'}
        action={retry && <Button onClick={retry}>重试</Button>}
      />
    )
  if (empty) return <Empty className="management-async-state" description={empty} />
  return <>{children}</>
}
export function StatusTag({
  published,
  changed,
}: {
  published: number | null
  changed: boolean
}) {
  return (
    <Tag
      className="management-status"
      data-state={changed ? 'changed' : published ? 'published' : 'unpublished'}
    >
      <span className="management-status-dot" aria-hidden="true" />
      {changed ? '有待发布变更' : published ? '已发布 v' + published : '未发布'}
    </Tag>
  )
}
