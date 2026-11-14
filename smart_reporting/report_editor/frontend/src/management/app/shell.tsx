import React, { useState } from 'react'
import {
  Breadcrumb,
  App,
  Button,
  Drawer,
  Dropdown,
  Layout,
  Menu,
} from 'antd'
import UserOutlined from '@ant-design/icons/UserOutlined'
import { ProductIdentity } from '../components/common'
import DatabaseOutlined from '@ant-design/icons/DatabaseOutlined'
import CommentOutlined from '@ant-design/icons/CommentOutlined'
import AuditOutlined from '@ant-design/icons/AuditOutlined'
import BarChartOutlined from '@ant-design/icons/BarChartOutlined'
import SettingOutlined from '@ant-design/icons/SettingOutlined'
import FormatPainterOutlined from '@ant-design/icons/FormatPainterOutlined'
import BookOutlined from '@ant-design/icons/BookOutlined'
import MenuFoldOutlined from '@ant-design/icons/MenuFoldOutlined'
import MenuUnfoldOutlined from '@ant-design/icons/MenuUnfoldOutlined'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useSession } from './session'
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
    [mobile, setMobile] = useState(false),
    [collapsed, setCollapsed] = useState(false),
    [logoutBusy, setLogoutBusy] = useState(false),
    { message } = App.useApp()
  const path = location.pathname.split('/').filter(Boolean)
  const breadcrumbs =
    path[0] === 'sources'
      ? [
          {
            title:
              path.length > 1 ? (
                <Link to="/sources">数据源</Link>
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
      : [{ title: path[0] === 'system-configuration' ? '系统配置' : path[0] === 'preferences' ? '偏好管理' : path[0] === 'knowledge' ? '业务知识' : path[0] === 'metrics' ? '业务指标' : path[0] === 'statistical-policies' ? '统计口径' : path[0] === 'report-issues' ? '报告问题' : '修改密码' }]
  const menu = (
    <Menu
      theme="light"
      inlineCollapsed={collapsed}
      mode="inline"
      selectedKeys={[
        location.pathname.startsWith('/system-configuration') ? 'system-configuration' : location.pathname.startsWith('/preferences') ? 'preferences' : location.pathname.startsWith('/knowledge') ? 'knowledge' : location.pathname.startsWith('/metrics') ? 'metrics' : location.pathname.startsWith('/statistical-policies') ? 'statistical-policies' : location.pathname.startsWith('/report-issues') ? 'report-issues' : 'sources',
      ]}
      items={[
        {
          key: 'sources',
          icon: <DatabaseOutlined />,
          label: <Link to="/sources">数据源</Link>,
        },
        { key: 'knowledge', icon: <BookOutlined />, label: <Link to="/knowledge">业务知识</Link> },
        { key: 'metrics', icon: <BarChartOutlined />, label: <Link to="/metrics">业务指标</Link> },
        { key: 'statistical-policies', icon: <AuditOutlined />, label: <Link to="/statistical-policies">统计口径</Link> },
        { key: 'report-issues', icon: <CommentOutlined />, label: <Link to="/report-issues">报告问题</Link> },
        { key: 'system-configuration', icon: <SettingOutlined />, label: <Link to="/system-configuration">系统配置</Link> },
        { key: 'preferences', icon: <FormatPainterOutlined />, label: <Link to="/preferences">偏好管理</Link> },
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
      <Drawer rootClassName="management-overlay"
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
          >
            菜单
          </Button>
          <Breadcrumb
            className="management-header-breadcrumb"
            items={breadcrumbs}
          />
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
              aria-label={`账号操作：${state.session?.username || ''}`}
            >
              {state.session?.username} ▾
            </Button>
          </Dropdown>
        </Header>
        <Content className="management-content">
          <Outlet />
        </Content>
        <footer className="management-footer">智能报告 · 管理工作台</footer>
      </Layout>
    </Layout>
  )
}
