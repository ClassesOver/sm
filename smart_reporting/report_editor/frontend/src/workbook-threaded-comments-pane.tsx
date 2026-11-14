// Full pane/entry/composer/hover UI ported from genoffice f8c17004 ThreadedCommentsPane.tsx.
import {createContext,useContext,useEffect,useRef,useState,useSyncExternalStore} from 'react'
import {formatAddress} from '@sheets-web/xlsx-engine'
import {parseThreadTimestamp,ThreadStore,ThreadPaneController,type CellThread,type ThreadReply} from './workbook-threaded-comments'
import type {ThreadHover} from './workbook-threaded-comment-marker'
import type {createUniver} from './workbook-vendor/grid/create-univer'
type UniverRuntime = ReturnType<typeof createUniver>
export const ThreadsContext = createContext<{threadStore:ThreadStore;threadPane:ThreadPaneController;editable:()=>boolean}|null>(null)
const labels: Record<string,string> = {
  appCommentsPaneTitle: '批注',
  appNoCommentsOnSheet: '当前工作表没有批注会话。',
  appThreadCancel: '取消',
  appThreadDelete: '删除',
  appThreadDeleteThread: '删除会话',
  appThreadEdit: '编辑',
  appThreadHoverHint: '在“批注”窗格中回复',
  appThreadNewPlaceholder: '开始对话',
  appThreadPost: '发布',
  appThreadReopen: '重新打开',
  appThreadReply: '回复',
  appThreadReplyPlaceholder: '回复…',
  appThreadResolve: '解决',
  appThreadResolved: '已解决',
  appThreadSave: '保存',
}
const t = (key:string) => labels[key] ?? key
function formatStamp(dT: string): string {
  const date = parseThreadTimestamp(dT)
  if (!date) return dT
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function useActiveSheetId(getRuntime: () => UniverRuntime | null): string | null {
  const [sheetId, setSheetId] = useState<string | null>(null)
  const {threadStore} = useContext(ThreadsContext)!
  const version = useSyncExternalStore(threadStore.subscribe, threadStore.getVersion)
  useEffect(() => {
    const runtime = getRuntime()
    if (!runtime) return
    setSheetId(runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheetId() ?? null)
    const disposable = runtime.univerAPI.addEvent(
      runtime.univerAPI.Event.ActiveSheetChanged,
      ({ activeSheet }: {activeSheet: any}) => setSheetId(activeSheet.getSheetId()),
    )
    return () => disposable.dispose()
    // A store reload (new file) may come with a new runtime.
  }, [getRuntime, version])
  return sheetId
}

function Composer({
  placeholder,
  initial = '',
  autoFocus = false,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  readonly placeholder: string
  readonly initial?: string
  readonly autoFocus?: boolean
  readonly submitLabel: string
  readonly onSubmit: (text: string) => void
  readonly onCancel?: () => void
}): React.JSX.Element {
  const {threadStore,threadPane,editable} = useContext(ThreadsContext)!
  const [text, setText] = useState(initial)
  const submit = (): void => {
    const trimmed = text.trim()
    if (trimmed.length === 0) return
    onSubmit(trimmed)
    setText('')
  }
  return (
    <div className="tc-composer">
      <textarea
        value={text}
        placeholder={placeholder}
        autoFocus={autoFocus}
        rows={2}
        // the comment box is the one real DOM edit surface in Sheets (Univer's
        // cell editor is canvas-rendered), so the native squiggle the spelling
        // preference promises can exist exactly here; read per mount, like
        // docs' header/footer editors
        spellCheck={true}
        maxLength={32000}
        disabled={!editable() || threadStore.isBusy()}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
            event.preventDefault()
            submit()
          } else if (event.key === 'Escape' && onCancel) {
            event.preventDefault()
            onCancel()
          }
        }}
      />
      <div className="tc-actions">
        {onCancel && (
          <button type="button" className="tc-button" onClick={onCancel}>
            {t('appThreadCancel')}
          </button>
        )}
        <button
          type="button"
          className="tc-button primary"
          disabled={text.trim().length === 0 || !editable() || threadStore.isBusy()}
          onClick={submit}
        >
          {submitLabel}
        </button>
      </div>
    </div>
  )
}

function Entry({
  author,
  dT,
  text,
  readOnly,
  onEdit,
  onDelete,
}: {
  readonly author: string
  readonly dT: string
  readonly text: string
  readonly readOnly: boolean
  readonly onEdit: (text: string) => void
  readonly onDelete: () => void
}): React.JSX.Element {
  const {threadStore,threadPane,editable} = useContext(ThreadsContext)!
  const [editing, setEditing] = useState(false)
  return (
    <div className="tc-entry">
      <div className="tc-entry-head">
        <span className="tc-author">{author}</span>
        <span className="tc-time">{formatStamp(dT)}</span>
      </div>
      {editing ? (
        <Composer
          placeholder=""
          initial={text}
          autoFocus
          submitLabel={t('appThreadSave')}
          onSubmit={(next) => {
            onEdit(next)
            setEditing(false)
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <div className="tc-text">{text}</div>
          {!readOnly && (
            <div className="tc-entry-tools">
              <button type="button" className="tc-link" onClick={() => setEditing(true)}>
                {t('appThreadEdit')}
              </button>
              <button type="button" className="tc-link" onClick={onDelete}>
                {t('appThreadDelete')}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ThreadCard({
  sheetId,
  thread,
  focused,
  onJump,
}: {
  readonly sheetId: string
  readonly thread: CellThread
  readonly focused: boolean
  readonly onJump: () => void
}): React.JSX.Element {
  const {threadStore,threadPane,editable} = useContext(ThreadsContext)!
  const ref = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [focused])
  const { row, column } = thread
  const canEdit=editable()&&!threadStore.readOnlyReason(sheetId)
  return (
    <article
      ref={ref}
      className={`tc-thread ${thread.done ? 'resolved' : ''} ${focused ? 'focused' : ''}`}
    >
      <header>
        <button type="button" className="tc-cell" onClick={onJump}>
          {formatAddress(row, column)}
        </button>
        {thread.done && <span className="tc-badge">{t('appThreadResolved')}</span>}
        <span className="tc-spacer" />
        <button
          type="button"
          className="tc-link"
          disabled={!canEdit || threadStore.isBusy()}
          onClick={() => threadStore.setDone(sheetId, row, column, !thread.done)}
        >
          {t(thread.done ? 'appThreadReopen' : 'appThreadResolve')}
        </button>
        <button
          type="button"
          className="tc-link danger"
          disabled={!canEdit || threadStore.isBusy()}
          onClick={() => threadStore.remove(sheetId, row, column)}
        >
          {t('appThreadDeleteThread')}
        </button>
      </header>
      <Entry
        author={thread.author}
        dT={thread.dT}
        text={thread.text}
        readOnly={thread.done || !canEdit || threadStore.isBusy()}
        onEdit={(text) => threadStore.editText(sheetId, row, column, thread.id, text)}
        onDelete={() => threadStore.remove(sheetId, row, column)}
      />
      {thread.replies.map((reply: ThreadReply) => (
        <Entry
          key={reply.id}
          author={reply.author}
          dT={reply.dT}
          text={reply.text}
          readOnly={thread.done || !canEdit || threadStore.isBusy()}
          onEdit={(text) => threadStore.editText(sheetId, row, column, reply.id, text)}
          onDelete={() => threadStore.deleteReply(sheetId, row, column, reply.id)}
        />
      ))}
      {!thread.done && canEdit && (
        <Composer
          placeholder={t('appThreadReplyPlaceholder')}
          autoFocus={focused}
          submitLabel={t('appThreadReply')}
          onSubmit={(text) => threadStore.reply(sheetId, row, column, text)}
        />
      )}
    </article>
  )
}

export function ThreadedCommentsPane({
  getRuntime, onJump,
}: {
  readonly getRuntime: () => UniverRuntime | null
  readonly onJump?: (sheetId:string,row:number,column:number)=>void
}): React.JSX.Element | null {
  const {threadStore,threadPane,editable} = useContext(ThreadsContext)!
  const pane = useSyncExternalStore(threadPane.subscribe, threadPane.getState)
  useSyncExternalStore(threadStore.subscribe, threadStore.getVersion)
  const sheetId = useActiveSheetId(getRuntime)
  if (!pane.open) return null
  const threads = threadStore.sheetThreads(sheetId)
  const draft = pane.draft && pane.draft.sheetId === sheetId ? pane.draft : null
  const jump = (row: number, column: number): void => {
    if(onJump&&sheetId){onJump(sheetId,row,column);return}
    const sheet = getRuntime()?.univerAPI.getActiveWorkbook()?.getActiveSheet()
    if (!sheet) return
    sheet.getRange(row, column, 1, 1).activate()
  }
  return (
    <aside className="threaded-comments-pane" aria-label={t('appCommentsPaneTitle')}>
      <header>
        <span>{t('appCommentsPaneTitle')}</span>
        <button
          type="button"
          className="tc-close"
          aria-label={t('appThreadCancel')}
          onClick={() => threadPane.close()}
        >
          ×
        </button>
      </header>
      <div className="tc-list">
        {threadStore.readOnlyReason(sheetId)&&<p className="tc-empty" role="status">此来源仅可保留：{threadStore.readOnlyReason(sheetId)}</p>}
        {draft && sheetId && (
          <article className="tc-thread focused">
            <header>
              <span className="tc-cell">{formatAddress(draft.row, draft.column)}</span>
            </header>
            <Composer
              key={`${draft.sheetId}:${draft.row}:${draft.column}`}
              placeholder={t('appThreadNewPlaceholder')}
              autoFocus
              submitLabel={t('appThreadPost')}
              onSubmit={(text) => {
                threadStore.add(sheetId, draft.row, draft.column, text)
                threadPane.clearDraft()
              }}
              onCancel={() => threadPane.clearDraft()}
            />
          </article>
        )}
        {threads.length === 0 && !draft && <p className="tc-empty">{t('appNoCommentsOnSheet')}</p>}
        {sheetId &&
          threads.map((thread) => (
            <ThreadCard
              key={thread.id}
              sheetId={sheetId}
              thread={thread}
              focused={
                pane.focus?.sheetId === sheetId &&
                pane.focus.row === thread.row &&
                pane.focus.column === thread.column
              }
              onJump={() => jump(thread.row, thread.column)}
            />
          ))}
      </div>
    </aside>
  )
}

export function ThreadHoverCard({
  hover,
}: {
  readonly hover: ThreadHover | null
}): React.JSX.Element | null {
  const {threadStore,threadPane,editable} = useContext(ThreadsContext)!
  if (!hover) return null
  const { thread } = hover
  const left = Math.min(hover.clientX + 14, Math.max(0, window.innerWidth - 300))
  const top = Math.min(hover.clientY + 14, Math.max(0, window.innerHeight - 200))
  return (
    <div className="thread-hover-card" style={{ left, top }} role="tooltip">
      <div className="tc-entry">
        <div className="tc-entry-head">
          <span className="tc-author">{thread.author}</span>
          <span className="tc-time">{formatStamp(thread.dT)}</span>
          {thread.done && <span className="tc-badge">{t('appThreadResolved')}</span>}
        </div>
        <div className="tc-text">{thread.text}</div>
      </div>
      {thread.replies.map((reply) => (
        <div key={reply.id} className="tc-entry reply">
          <div className="tc-entry-head">
            <span className="tc-author">{reply.author}</span>
            <span className="tc-time">{formatStamp(reply.dT)}</span>
          </div>
          <div className="tc-text">{reply.text}</div>
        </div>
      ))}
      <div className="tc-hint">{t('appThreadHoverHint')}</div>
    </div>
  )
}
