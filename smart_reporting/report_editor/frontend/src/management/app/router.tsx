import { lazy, Suspense, useEffect } from 'react'
import { Alert, Button, Skeleton } from 'antd'
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  useLocation,
  useRouteError,
} from 'react-router-dom'
import { useSession } from './session'
const Shell = lazy(() => import('./shell'))
const Login = lazy(() => import('../features/auth/login'))
const Sources = lazy(() => import('../features/sources/list'))
const Detail = lazy(() => import('../features/sources/detail'))
const Editor = lazy(() => import('../features/sources/editor'))
const Password = lazy(() => import('../features/auth/password'))
const ReportIssues = lazy(() => import('../features/issues/page'))
const Policies = lazy(() => import('../features/policies/page'))
const Metrics = lazy(() => import('../features/metrics/page'))
const Knowledge = lazy(() => import('../features/knowledge/page'))
const SystemConfiguration = lazy(() => import('../features/configuration/system'))
const Preferences = lazy(() => import('../features/configuration/preferences'))
function Boundary() {
  const { state, load } = useSession(),
    location = useLocation()
  useEffect(() => {
    const label =
      location.pathname === '/login'
        ? '登录'
        : location.pathname.includes('/edit')
          ? '编辑数据源'
          : location.pathname.endsWith('/new')
            ? '新建数据源'
            : location.pathname.startsWith('/system-configuration')
            ? '系统配置'
          : location.pathname.startsWith('/preferences')
            ? '偏好管理'
          : location.pathname.startsWith('/knowledge')
              ? '业务知识'
            : location.pathname.startsWith('/metrics')
              ? '业务指标'
            : location.pathname.startsWith('/statistical-policies')
              ? '统计口径'
            : location.pathname.startsWith('/report-issues')
              ? '报告问题'
                : location.pathname.startsWith('/account')
                ? '修改密码'
                : location.pathname === '/sources'
                  ? '数据源'
                  : '数据源详情'
    document.title = label + ' · Smart Reporting'
  }, [location.pathname])
  if (state.status === 'loading') return <Skeleton active />
  if (state.status === 'unavailable')
    return (
      <Alert
        type="error"
        title={state.error}
        action={<Button onClick={() => void load()}>重试</Button>}
      />
    )
  if (state.status === 'anonymous' && location.pathname !== '/login')
    return (
      <Navigate
        replace
        to={
          '/login?' +
          new URLSearchParams({
            returnTo: '/management' + location.pathname + location.search,
          })
        }
      />
    )
  return (
    <Suspense fallback={<Skeleton active />}>
      <Outlet />
    </Suspense>
  )
}
function RouteError() {
  const error = useRouteError()
  return (
    <Alert
      type="error"
      title="页面无法打开"
      description={
        error instanceof Error
          ? error.message
          : '请检查页面地址，或返回数据源列表。'
      }
      action={<a href="/management/sources">返回数据源</a>}
    />
  )
}
export function makeRouter() {
  return createBrowserRouter(
    [
      {
        element: <Boundary />,
        errorElement: <RouteError />,
        children: [
          { path: 'login', element: <Login /> },
          {
            element: <Shell />,
            children: [
              { index: true, element: <Navigate to="/sources" replace /> },
              { path: 'sources', element: <Sources /> },
              { path: 'sources/new', element: <Editor /> },
              { path: 'sources/:sourceId', element: <Detail /> },
              { path: 'sources/:sourceId/view', element: <Detail /> },
              { path: 'sources/:sourceId/edit', element: <Editor /> },
              { path: 'report-issues', element: <ReportIssues /> },
              { path: 'statistical-policies', element: <Policies /> },
              { path: 'metrics', element: <Metrics /> },
              { path: 'knowledge', element: <Knowledge /> },
              { path: 'system-configuration', element: <SystemConfiguration /> },
              { path: 'preferences', element: <Preferences /> },
              { path: 'account/password', element: <Password /> },
            ],
          },
        ],
      },
    ],
    { basename: '/management' },
  )
}
