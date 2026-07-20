import { Check, Copy } from 'lucide-react'
import { Children, isValidElement, ReactNode, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { IconButton } from './IconButton'

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const child = Children.only(children)
  if (!isValidElement<{ className?: string; children?: ReactNode }>(child)) {
    return <pre>{children}</pre>
  }
  const language = child.props.className?.match(/language-([\w-]+)/)?.[1]
  const code = String(child.props.children || '').replace(/\n$/, '')
  const copy = async () => {
    await navigator.clipboard?.writeText(code)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }
  return (
    <div className="agui-code-block">
      <div className="agui-code-toolbar">
        <span>{language || 'text'}</span>
        <IconButton label="复制代码" className="rounded border-0 text-inherit hover:bg-white/10 hover:text-inherit" onClick={() => void copy()}>
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </IconButton>
      </div>
      <pre>{child}</pre>
    </div>
  )
}

export function Markdown({ children }: { children: string }) {
  return (
    <div className="agui-markdown text-sm leading-6 text-secondary">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: CodeBlock,
          a({ href, children: linkChildren, ...rest }) {
            const external = !!href && /^(https?:)?\/\//i.test(href)
            return (
              <a
                {...rest}
                href={href}
                target={external ? '_blank' : undefined}
                rel={external ? 'noopener noreferrer' : undefined}
              >
                {linkChildren}
              </a>
            )
          }
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
