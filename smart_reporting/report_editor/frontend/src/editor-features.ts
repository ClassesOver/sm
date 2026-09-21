import { CrepeBuilder } from '@milkdown/crepe/builder'
import { ai } from '@milkdown/crepe/feature/ai'
import type { AIFeatureConfig } from '@milkdown/crepe/feature/ai'
import { blockEdit } from '@milkdown/crepe/feature/block-edit'
import { cursor } from '@milkdown/crepe/feature/cursor'
import { linkTooltip } from '@milkdown/crepe/feature/link-tooltip'
import { listItem } from '@milkdown/crepe/feature/list-item'
import { placeholder } from '@milkdown/crepe/feature/placeholder'
import { table } from '@milkdown/crepe/feature/table'
import { toolbar } from '@milkdown/crepe/feature/toolbar'

import { editorChineseLocale } from './localization'

export function createReportEditor(
  root: Node,
  defaultValue: string,
  aiConfig: AIFeatureConfig,
): CrepeBuilder {
  return new CrepeBuilder({
    root,
    defaultValue,
  })
    .addFeature(cursor)
    .addFeature(listItem)
    .addFeature(linkTooltip, editorChineseLocale.linkTooltip)
    .addFeature(blockEdit, editorChineseLocale.blockEdit)
    .addFeature(placeholder, { text: '开始编辑报告…' })
    .addFeature(toolbar, editorChineseLocale.toolbar)
    .addFeature(table)
    .addFeature(ai, aiConfig)
}
