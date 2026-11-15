import { officeRequest, type OfficeSpace, type OfficeUser } from './office-client'

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text = '') {
  const node = document.createElement(tag)
  node.textContent = text
  return node
}

function button(label: string, action: () => Promise<void>, status: HTMLElement) {
  const control = element('button', label)
  control.type = 'button'
  control.onclick = async () => {
    control.disabled = true
    try { await action(); status.textContent = '' }
    catch (error) { status.textContent = error instanceof Error ? error.message : '操作失败。' }
    finally { control.disabled = false }
  }
  return control
}

export async function showOfficeAdministration(
  host: HTMLElement, options: { user: OfficeUser; space?: OfficeSpace; onChanged(): Promise<void> },
) {
  const panel = element('dialog')
  panel.className = 'office-administration'
  const heading = element('h2', options.space ? '工作区成员' : '用户管理')
  const status = element('p')
  status.setAttribute('role', 'status')
  const list = element('div')
  const close = element('button', '关闭')
  close.onclick = () => panel.close()
  panel.onclose = () => panel.remove()
  panel.addEventListener('click', event => event.stopPropagation())
  panel.append(heading, list, status, close)
  host.append(panel)
  panel.showModal()

  async function refresh() {
    list.replaceChildren()
    if (options.space) {
      const result = await officeRequest<{ items: { user: string; name: string; role: string }[] }>(
        `/workspaces/${options.space.id}/members`)
      for (const member of result.items) {
        const row = element('div')
        row.className = 'office-admin-row'
        const role = element('select')
        role.setAttribute('aria-label', `${member.name}的工作区角色`)
        for (const [value, text] of [['owner', '负责人'], ['editor', '编辑者'], ['viewer', '查看者']]) {
          const option = element('option', text)
          option.value = value
          option.selected = member.role === value
          role.append(option)
        }
        row.append(element('span', member.name), role, button('保存', async () => {
          await officeRequest(`/workspaces/${options.space!.id}/members/${encodeURIComponent(member.user)}`,
            'PUT', { role: role.value })
          await options.onChanged()
        }, status), button('移除', async () => {
          if (!confirm(`移除成员“${member.name}”？`)) return
          await officeRequest(`/workspaces/${options.space!.id}/members/${encodeURIComponent(member.user)}`,
            'PUT', { role: null })
          await refresh()
          await options.onChanged()
        }, status))
        list.append(row)
      }
    } else {
      const result = await officeRequest<{ items: OfficeUser[] }>('/admin/users')
      for (const user of result.items) {
        const row = element('div')
        row.className = 'office-admin-row'
        row.append(element('span', `${user.name}（${user.user}）`),
          element('span', user.role === 'admin' ? '公司管理员' : '普通用户'),
          button(user.enabled ? '停用' : '启用', async () => {
            await officeRequest(`/admin/users/${encodeURIComponent(user.user)}`, 'PATCH', { enabled: !user.enabled })
            await refresh()
          }, status),
          button(user.role === 'admin' ? '设为普通用户' : '设为管理员', async () => {
            await officeRequest(`/admin/users/${encodeURIComponent(user.user)}`, 'PATCH',
              { role: user.role === 'admin' ? 'user' : 'admin' })
            await refresh()
          }, status),
          button('重置密码', async () => {
            const dialog = element('dialog')
            dialog.className = 'office-administration'
            dialog.addEventListener('click', event => event.stopPropagation())
            const form = element('form')
            const password = element('input')
            password.type = 'password'
            password.autocomplete = 'new-password'
            password.minLength = 12
            password.maxLength = 256
            password.required = true
            password.setAttribute('aria-label', '新密码')
            const save = element('button', '保存')
            save.type = 'submit'
            const feedback = element('p')
            feedback.setAttribute('role', 'status')
            form.append(password, save, button('取消', async () => { dialog.close() }, feedback))
            form.onsubmit = async event => {
              event.preventDefault()
              save.disabled = true
              try {
                await officeRequest(`/admin/users/${encodeURIComponent(user.user)}/password`,
                  'PUT', { password: password.value })
                dialog.close()
                status.textContent = '密码已重置，旧会话已失效。'
              } catch (error) {
                feedback.textContent = error instanceof Error ? error.message : '密码重置失败。'
              } finally { save.disabled = false }
            }
            dialog.onclose = () => dialog.remove()
            dialog.append(element('h2', `重置 ${user.name} 的密码`), form, feedback)
            list.closest('dialog')!.append(dialog)
            dialog.showModal()
          }, status),
          button('撤销会话', async () => {
            await officeRequest(`/admin/users/${encodeURIComponent(user.user)}/revoke-sessions`, 'POST')
          }, status))
        list.append(row)
      }
    }
    const form = element('form')
    const identity = element('input')
    identity.placeholder = '工作区用户 ID'
    identity.setAttribute('aria-label', '工作区用户 ID')
    identity.required = true
    const name = element('input')
    name.placeholder = '显示名称'
    name.setAttribute('aria-label', '显示名称')
    name.required = true
    const submit = element('button', options.space ? '添加成员' : '开通用户')
    submit.type = 'submit'
    form.append(identity)
    const password = element('input')
    password.type = 'password'
    password.autocomplete = 'new-password'
    password.minLength = 12
    password.maxLength = 256
    password.required = true
    password.placeholder = '初始密码'
    password.setAttribute('aria-label', '初始密码')
    if (!options.space) form.append(name, password)
    form.append(submit)
    form.onsubmit = async event => {
      event.preventDefault()
      submit.disabled = true
      try {
        if (options.space) {
          await officeRequest(`/workspaces/${options.space.id}/members/${encodeURIComponent(identity.value.trim())}`,
            'PUT', { role: 'viewer' })
        } else {
          await officeRequest('/admin/users', 'POST', { user: identity.value.trim(), name: name.value.trim(), password: password.value })
        }
        await refresh()
      } catch (error) { status.textContent = error instanceof Error ? error.message : '操作失败。' }
      finally { submit.disabled = false }
    }
    list.append(form)
    if (options.space) {
      const section = element('section')
      const name = element('input')
      name.value = options.space.name
      name.setAttribute('aria-label', '工作区名称')
      section.append(element('h3', '工作区设置'), name, button('保存名称', async () => {
        await officeRequest(`/workspaces/${options.space!.id}`, 'PATCH', { name: name.value.trim() })
        options.space!.name = name.value.trim()
        await options.onChanged()
      }, status), button(options.space.archived ? '恢复工作区' : '归档为只读', async () => {
        const archived = !options.space!.archived
        await officeRequest(`/workspaces/${options.space!.id}`, 'PATCH', { archived })
        options.space!.archived = archived
        await options.onChanged(); await refresh()
      }, status))
      list.append(section)
    }
  }
  try { await refresh() }
  catch (error) { status.textContent = error instanceof Error ? error.message : '读取失败。' }
}
