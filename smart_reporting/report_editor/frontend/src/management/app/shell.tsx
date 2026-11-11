import React, { useState } from 'react'
import {
  Alert,
  Breadcrumb,
  App,
  Button,
  Drawer,
  Dropdown,
  Layout,
  Menu,
  Select,
} from 'antd'
import UserOutlined from '@ant-design/icons/UserOutlined'
import { ProductIdentity } from '../components/common'
import DatabaseOutlined from '@ant-design/icons/DatabaseOutlined'
import ApartmentOutlined from '@ant-design/icons/ApartmentOutlined'
import CommentOutlined from '@ant-design/icons/CommentOutlined'
import AuditOutlined from '@ant-design/icons/AuditOutlined'
import BarChartOutlined from '@ant-design/icons/BarChartOutlined'
import BookOutlined from '@ant-design/icons/BookOutlined'
import MenuFoldOutlined from '@ant-design/icons/MenuFoldOutlined'
import MenuUnfoldOutlined from '@ant-design/icons/MenuUnfoldOutlined'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useSession } from './session'
import { useScopes } from '../features/scopes/queries'
import { request, emptySchema } from '../api/http'
const { Header, Sider, Content } = Layout
export default function ShellProvider() {
  return (
    <App>
      <Shell />
    </App>
  )
}
function Shell() {
  const location = useLocation(),
    navigate = useNavigate(),
    { state, clear } = useSession(),
    scopes = useScopes(),
    [mobile, setMobile] = useState(false),
    [collapsed, setCollapsed] = useState(false),
    [logoutBusy, setLogoutBusy] = useState(false),
    { message } = App.useApp()
  const params = new URLSearchParams(location.search),
    selected =
      params.get('database') && params.get('companyId')
        ? JSON.stringify([params.get('database'), params.get('companyId')])
        : undefined
  const options =
    scopes.data?.pages
      .flatMap((p) => p.items)
      .map((s) => ({
        value: JSON.stringify([s.database, s.companyId]),
        label: s.name,
        description: s.database + ' / ' + s.companyId,
      })) || []
  if (selected && !options.some((option) => option.value === selected))
    options.unshift({
      value: selected,
      label: params.get('database') + ' / ' + params.get('companyId'),
      description: '当前作用域',
    })
  const path = location.pathname.split('/').filter(Boolean)
  const breadcrumbs =
    path[0] === 'sources'
      ? [
          {
            title:
              path.length > 1 ? (
                <Link to={'/sources' + location.search}>数据源</Link>
              ) : (
                '数据源'
              ),
          },
          ...(path.length > 1
            ? [
                {
                  title:
                    path[1] === 'new' && path.length === 2
                      ? '新建'
                      : decodeURIComponent(path[1]),
                },
              ]
            : []),
          ...(path[2] === 'edit' ? [{ title: '编辑草稿' }] : []),
        ]
      : [{ title: path[0] === 'knowledge' ? '业务知识' : path[0] === 'metrics' ? '业务指标' : path[0] === 'statistical-policies' ? '统计口径' : path[0] === 'report-issues' ? '报告问题' : path[0] === 'organizations' ? '组织' : '修改密码' }]
  const menu = (
    <Menu
      theme="light"
      inlineCollapsed={collapsed}
      mode="inline"
      selectedKeys={[
        location.pathname.startsWith('/knowledge') ? 'knowledge' : location.pathname.startsWith('/metrics') ? 'metrics' : location.pathname.startsWith('/statistical-policies') ? 'statistical-policies' : location.pathname.startsWith('/report-issues') ? 'report-issues' : location.pathname.startsWith('/organizations')
          ? 'organizations'
          : 'sources',
      ]}
      items={[
        { key: 'knowledge', icon: <BookOutlined />, label: <Link to={'/knowledge' + location.search}>业务知识</Link> },
        { key: 'metrics', icon: <BarChartOutlined />, label: <Link to={'/metrics' + location.search}>业务指标</Link> },
        { key: 'statistical-policies', icon: <AuditOutlined />, label: <Link to={'/statistical-policies' + location.search}>统计口径</Link> },
        { key: 'report-issues', icon: <CommentOutlined />, label: <Link to={'/report-issues' + location.search}>报告问题</Link> },
        {
          key: 'sources',
          icon: <DatabaseOutlined />,
          label: <Link to={'/sources' + location.search}>数据源</Link>,
        },
        {
          key: 'organizations',
          icon: <ApartmentOutlined />,
          label: <Link to="/organizations">组织</Link>,
        },
      ]}
      onClick={() => setMobile(false)}
    />
  )
  return (
    <Layout className="management-layout">
      <Sider
        width={208}
        collapsed={collapsed}
        onBreakpoint={setCollapsed}
        breakpoint="lg"
        collapsedWidth={64}
        className="management-sider"
      >
        <div className="management-logo">
          <ProductIdentity />
        </div>
        <div className="management-nav-label" aria-hidden="true">
          工作空间
        </div>
        {menu}
        <div className="management-nav-footer">
          <span className="management-nav-caption">配置与版本管理</span>
          <Button
            className="management-collapse"
            type="text"
            aria-label={collapsed ? '展开导航' : '收起导航'}
            onClick={() => setCollapsed(!collapsed)}
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          />
        </div>
      </Sider>
      <Drawer
        open={mobile}
        title="管理工作台"
        placement="left"
        onClose={() => setMobile(false)}
      >
        {React.cloneElement(menu, { inlineCollapsed: false })}
      </Drawer>
      <Layout className="management-workspace">
        <Header className="management-header">
          <Button
            className="management-mobile-menu"
            onClick={() => setMobile(true)}
            aria-label="打开导航"
          >
            菜单
          </Button>
          <Breadcrumb
            className="management-header-breadcrumb"
            items={breadcrumbs}
          />
          <div className="management-scope">
            <label htmlFor="management-scope">当前组织</label>
            <Select
              id="management-scope"
              aria-label="当前组织"
              placeholder="请选择组织"
              value={selected}
              loading={scopes.isPending}
              showSearch
              optionFilterProp="label"
              onChange={(value) => {
                const [database, companyId] = JSON.parse(value)
                navigate(
                  (location.pathname.startsWith('/knowledge') ? '/knowledge?' : location.pathname.startsWith('/metrics') ? '/metrics?' : location.pathname.startsWith('/statistical-policies') ? '/statistical-policies?' : location.pathname.startsWith('/report-issues') ? '/report-issues?' : '/sources?') + new URLSearchParams({ database, companyId }),
                )
              }}
              options={options}
              optionRender={(option) => (
                <div className="management-scope-option">
                  <strong>{option.label}</strong>
                  <small>{option.data.description}</small>
                </div>
              )}
              popupRender={(node) => (
                <>
                  {node}
                  {scopes.hasNextPage && (
                    <Button
                      block
                      onClick={() => void scopes.fetchNextPage()}
                      loading={scopes.isFetchingNextPage}
                    >
                      加载更多组织
                    </Button>
                  )}
                </>
              )}
            />
          </div>
          <Dropdown
            menu={{
              items: [
                { key: 'password', label: '修改密码' },
                { key: 'logout', label: '退出登录', disabled: logoutBusy },
              ],
              onClick: async ({ key }) => {
                if (key === 'password') {
                  navigate('/account/password')
                  return
                }
                setLogoutBusy(true)
                try {
                  await request('/auth/logout', emptySchema, {
                    method: 'POST',
                    csrf: state.session!.csrfToken,
                  })
                  clear('已退出登录。')
                } catch (e) {
                  void message.error((e as Error).message)
                } finally {
                  setLogoutBusy(false)
                }
              },
            }}
          >
            <Button
              type="text"
              className="management-account"
              icon={<UserOutlined />}
              aria-label="账号操作"
            >
              {state.session?.username} ▾
            </Button>
          </Dropdown>
        </Header>
        <Content className="management-content">
          {scopes.error && (
            <Alert
              type="error"
              title={scopes.error.message}
              action={
                <Button onClick={() => void scopes.refetch()}>
                  重试组织读取
                </Button>
              }
            />
          )}
          <Outlet />
        </Content>
        <footer className="management-footer">智能报告 · 管理工作台</footer>
      </Layout>
    </Layout>
  )
}
