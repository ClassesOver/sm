import { useState } from 'react'
import { Alert, Button, Drawer } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'

const coordinate = z.number().int().positive().nullable()
const locatorSchema = z.object({ kind: z.enum(['text_lines', 'pdf_page', 'docx_paragraph', 'docx_table_cell']),
  lineStart: coordinate, lineEnd: coordinate, page: coordinate, paragraph: coordinate, table: coordinate, row: coordinate, column: coordinate })
const documentSchema = z.object({ documentId: z.string(), revisions: z.array(z.object({
  revision: z.number().int().positive(), metadata: z.object({ title: z.string() }), originalHash: z.string().min(1),
  reviewStatus: z.string(), ingestionStatus: z.string(),
  parseReceipt: z.object({ originalHash: z.string().min(1), fragments: z.array(z.object({ text: z.string(), locator: locatorSchema })) }).nullable(),
})) })

function locationLabel(locator: z.infer<typeof locatorSchema>) {
  if (locator.kind === 'text_lines' && locator.lineStart && locator.lineEnd && locator.lineEnd >= locator.lineStart) return `第${locator.lineStart}–${locator.lineEnd}行`
  if (locator.kind === 'pdf_page' && locator.page) return `第${locator.page}页`
  if (locator.kind === 'docx_paragraph' && locator.paragraph) return `第${locator.paragraph}段`
  if (locator.kind === 'docx_table_cell' && locator.table && locator.row && locator.column) return `表${locator.table}，第${locator.row}行、第${locator.column}列`
  return '位置记录不完整，请核对原件'
}

export function BusinessDocumentPreview({ scope, documentId, revision, reviewMode = false, kind = 'rule_evidence', onClose }: {
  scope: { database: string; companyId: string }; documentId: string; revision: number; reviewMode?: boolean; kind?: 'rule_evidence' | 'background'; onClose: () => void
}) {
  const [visible, setVisible] = useState(20)
  const document = useQuery({ queryKey: ['business-document-preview', scope, documentId, revision], retry: false, refetchOnMount: 'always',
    queryFn: ({ signal }) => request('/business-documents/' + encodeURIComponent(documentId) + '?' + scopeQuery(scope), documentSchema, { signal }) })
  const target = document.data?.documentId === documentId ? document.data.revisions.find(item => item.revision === revision) : undefined
  const issue = !target ? '未找到所选原件的精确修订，请核对文档身份。'
    : target.reviewStatus === 'revoked' ? '修订已撤销，不能展示为当前制度依据。'
    : (!reviewMode && (target.reviewStatus !== 'approved' || target.ingestionStatus !== 'ready'))
      || !['parsed', 'ready'].includes(target.ingestionStatus) || !target.parseReceipt ? '所选修订尚未审核或解析未就绪。'
    : target.parseReceipt.originalHash !== target.originalHash ? '解析与原件身份不一致，请核对原件。' : ''
  return <Drawer open title={(kind === 'background' ? '背景材料' : '制度原文') + `解析预览 · ${documentId} · 修订 ${revision}`} onClose={onClose} size={640}>
    <AsyncState loading={document.isFetching} error={document.error} retry={() => void document.refetch()}>
      {issue ? <Alert type="warning" title={issue} /> : target && <>
        <h3>{target.metadata.title}</h3>
        {reviewMode && <Alert type="info" title="管理审核预览：尚未作为已发布制度依据，核对原件后再决定审核。" />}
        <p>以下为本次读取的精确修订解析片段及登记位置，未生成业务解释；解析预览不能替代原件复核。</p>
        <div role="region" aria-label="制度原文解析片段" tabIndex={0} style={{ overflowWrap: 'anywhere' }}>
          {target.parseReceipt!.fragments.slice(0, visible).map((fragment, index) => <section key={index}>
            <h4>解析片段 {index + 1} · {locationLabel(fragment.locator)}</h4>
            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>{fragment.text.slice(0, 10000)}</pre>
            {fragment.text.length > 10000 && <p>此片段较长，仅预览前10000字，请结合原件核对全文。</p>}
          </section>)}
          {!target.parseReceipt!.fragments.length && <p>该修订没有可预览的解析片段。</p>}
        </div>
        {target.parseReceipt!.fragments.length > visible && <Button onClick={() => setVisible(count => count + 20)}>显示更多解析片段</Button>}
      </>}
    </AsyncState>
  </Drawer>
}
