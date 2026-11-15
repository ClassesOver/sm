// Capability/provider/model/key/base URL arrangement adapted from GenOffice SettingsModal.tsx.
// Source revision and license: smart_reporting/office/PROVIDERS-SOURCE.md.
import { officeRequest } from './office-client'
export type Capability = 'imageAnalysis' | 'videoAnalysis' | 'webSearch'
type Provider = { id: string; label: string; model: string; baseUrl: string }
type Configuration = { enabled: boolean; provider: string; model: string; baseUrl: string; version: number; hasKey: boolean }
type Catalog = { settings: Record<Capability, Configuration>; catalog: Record<Capability, Provider[]>; credentialStorageAvailable: boolean }
const titles: Record<Capability, string> = { imageAnalysis: '图片分析', videoAnalysis: '视频分析', webSearch: '联网搜索' }
function element<K extends keyof HTMLElementTagNameMap>(tag: K, content = '') { const node = document.createElement(tag); node.textContent = content; return node }

export async function mountOfficeProviderSettings(host: HTMLElement, options: {
  capabilities: Capability[]; onDirty(value: boolean): void; onBusy(value: boolean): void;
}) {
  if (!host.isConnected) return
  host.textContent = '正在加载提供商配置…'
  let catalog: Catalog
  try { catalog = await officeRequest<Catalog>('/admin/providers') }
  catch (error) {
    if (!host.isConnected) return
    host.textContent = (error as Error).message
    const retry = element('button', '重新加载提供商'); retry.type = 'button'
    retry.onclick = () => void mountOfficeProviderSettings(host, options); host.append(retry); return
  }
  if (!host.isConnected) return
  host.replaceChildren(); host.className = 'office-provider-settings'
  const dirty = new Map<Capability, boolean>()
  let busy = false
  const notifyDirty = () => options.onDirty([...dirty.values()].some(Boolean))
  if (!catalog.credentialStorageAvailable) {
    const warning = element('p', '密钥存储尚未启用。请部署管理员配置 AGENT_MANAGEMENT_CREDENTIAL_KEYS 后再保存 API Key。')
    warning.setAttribute('role', 'status'); host.append(warning)
  }
  for (const capability of options.capabilities) {
    const card = element('section'); card.className = 'office-provider-card'; card.setAttribute('aria-label', titles[capability]); host.append(card)
    let saved = catalog.settings[capability], draft = { ...saved }, apiKey: string | null = null, testFile: File | undefined
    const changed = () => {
      dirty.set(capability, JSON.stringify(draft) !== JSON.stringify(saved) || apiKey !== null)
      notifyDirty()
    }
    const draw = (message = '') => {
      card.replaceChildren(); card.append(element('h3', titles[capability]))
      const form = element('form'), status = element('p'); status.setAttribute('role', 'status'); status.textContent = message
      const field = (label: string, input: HTMLElement) => { const row = element('label'); row.className = 'office-provider-field'; row.append(element('span', label), input); input.setAttribute('aria-label', label); form.append(row) }
      const enabled = element('input'); enabled.type = 'checkbox'; enabled.checked = draft.enabled
      enabled.onchange = () => { draft.enabled = enabled.checked; status.textContent = '有未保存的修改'; changed() }
      field(`启用${titles[capability]}`, enabled)
      const select = element('select')
      for (const provider of catalog.catalog[capability]) select.add(new Option(provider.label, provider.id))
      select.value = draft.provider
      select.onchange = () => {
        const provider = catalog.catalog[capability].find(value => value.id === select.value)!
        draft = { ...draft, provider: provider.id, model: provider.model, baseUrl: provider.baseUrl, hasKey: false }
        apiKey = null; changed(); draw('提供商已切换，请填写该服务的 API Key。')
      }
      field('提供商', select)
      if (capability !== 'webSearch') {
        const model = element('input'); model.value = draft.model; model.maxLength = 200; model.required = true
        model.oninput = () => { draft.model = model.value.trim(); status.textContent = '有未保存的修改'; changed() }
        field('模型', model)
      }
      const key = element('input'); key.type = 'password'; key.autocomplete = 'new-password'; key.maxLength = 4096; key.value = apiKey ?? ''
      key.placeholder = saved.hasKey && saved.provider === draft.provider && saved.baseUrl === draft.baseUrl ? '已配置，留空保持现有密钥' : '请输入 API Key'
      key.oninput = () => { apiKey = key.value || null; status.textContent = '有未保存的修改'; changed() }
      field('API Key', key)
      const clear = element('button', '清除已存密钥'); clear.type = 'button'; clear.disabled = !saved.hasKey
      clear.onclick = () => { apiKey = ''; draft.enabled = false; changed(); draw('保存后将清除密钥并停用此能力。') }; form.append(clear)
      const base = element('input'); base.type = 'url'; base.required = true; base.value = draft.baseUrl; base.maxLength = 2048
      base.oninput = () => { draft.baseUrl = base.value.trim(); key.placeholder = saved.baseUrl === draft.baseUrl && saved.provider === draft.provider && saved.hasKey ? '已配置，留空保持现有密钥' : '地址已变化，请输入该服务的密钥'; status.textContent = '有未保存的修改'; changed() }
      field('服务地址', base)
      const note = element('p', capability === 'webSearch' ? '文档助手需要联网资料时使用此提供商；本地文件搜索由下方开关单独控制。' : '文档助手使用此提供商分析图片或视频；支持公网 HTTPS 地址和提供的文件内容，每次最多 4 个、合计 20 MiB。')
      note.className = 'office-provider-note'; form.append(note)
      if (capability !== 'webSearch') {
        const file = element('input'); file.type = 'file'; file.accept = capability === 'imageAnalysis' ? 'image/png,image/jpeg,image/webp,image/gif' : 'video/mp4,video/webm'
        file.onchange = () => { testFile = file.files?.[0]; status.textContent = testFile ? `测试文件：${testFile.name}` : '' }
        field('测试文件', file)
        if (testFile) form.append(element('p', `已选择：${testFile.name}`))
      }
      const actions = element('div'); actions.className = 'office-provider-actions'
      const save = element('button', `保存${titles[capability]}`); save.type = 'submit'
      const test = element('button', `测试${titles[capability]}`); test.type = 'button'
      const reload = element('button', '重新加载'); reload.type = 'button'
      reload.onclick = async () => {
        if (busy || ([...dirty.values()].some(Boolean) && !window.confirm('重新加载将放弃当前页面未保存的提供商修改，是否继续？'))) return
        options.onDirty(false); await mountOfficeProviderSettings(host, options)
      }
      actions.append(save, test, reload); form.append(actions, status); card.append(form)
      const run = async (testing: boolean) => {
        if (busy || !form.reportValidity()) return
        if (testing && capability !== 'webSearch' && !testFile) { status.textContent = '请选择测试文件，以验证实际分析能力。'; return }
        if (testing && testFile && testFile.size > 20 * 1024 * 1024) { status.textContent = '测试文件不得超过 20 MiB。'; return }
        busy = true; options.onBusy(true)
        const controls = [...host.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>('input, select, button')].map(control => ({control, disabled:control.disabled}))
        controls.forEach(({control}) => { control.disabled = true })
        status.textContent = testing ? '正在测试，测试不会保存配置…' : '正在保存…'
        try {
          const body = { enabled: draft.enabled, provider: draft.provider, model: draft.model, baseUrl: draft.baseUrl, apiKey, expectedVersion: saved.version }
          if (testing) {
            const media: string[] = []
            if (capability !== 'webSearch' && testFile) media.push(await new Promise<string>((resolve,reject) => {
              const reader = new FileReader(); reader.onload = () => resolve(reader.result as string); reader.onerror = () => reject(new Error('无法读取测试文件。')); reader.readAsDataURL(testFile!)
            }))
            const result = await officeRequest<{message:string}>(`/admin/providers/${capability}/test`, 'POST', {...body, media})
            if (host.isConnected) status.textContent = result.message
          } else {
            const value = await officeRequest<Configuration>(`/admin/providers/${capability}`, 'PUT', body)
            if (host.isConnected) { saved = value; draft = {...value}; apiKey = null; changed(); draw('已保存，对后续任务生效。') }
          }
        } catch (error) { if (host.isConnected) status.textContent = (error as Error).message }
        finally { busy = false; controls.forEach(({control,disabled}) => {control.disabled=disabled}); options.onBusy(false) }
      }
      form.onsubmit = event => {event.preventDefault();void run(false)}
      test.onclick = () => void run(true)
    }
    draw()
  }
}
