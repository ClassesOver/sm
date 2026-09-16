import type { OutlineItem } from './outline'

export function headingStructureStatus(items: OutlineItem[]) {
  let jumps = 0
  items.forEach((item, index) => {
    const previousLevel = items[index - 1]?.level ?? item.level
    if (item.level > previousLevel + 1) jumps += 1
  })
  return jumps
    ? { label: `标题层级跳跃 ${jumps} 处`, warning: true }
    : { label: '结构正常', warning: false }
}
