// Local adaptation: only unchanged upstream Markdown export protocol definitions.
export interface MarkdownImage {
  /** file name inside the media folder */
  name: string
  /** data: URL or lazy docx-media URL the main process resolves */
  src: string
}

/**
 * Folder token the Markdown references pictures under; the writer swaps it
 * for the real `<file>_files` folder once the save path is known. User text
 * can never spell it: `_` is escaped on the way out.
 */
export const MARKDOWN_MEDIA_DIR_TOKEN = '__genoffice_media__'

export type { AgentToolDef } from '@genoffice/agent-core/types'
