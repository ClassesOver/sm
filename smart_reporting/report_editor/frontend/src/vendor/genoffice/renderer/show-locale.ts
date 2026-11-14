/** Fixed source panes/zh.ts labels; uses the native host's current Chinese locale. */
const messages: Record<string, string> = {
  paneShowEndedClick: '放映结束，单击退出。', paneShowMenuNext: '下一页', paneShowMenuPrev: '上一页',
  paneShowMenuLastViewed: '上次查看的', paneShowMenuSeeAll: '查看所有幻灯片', paneShowMenuScreen: '屏幕',
  paneShowMenuBlack: '黑屏', paneShowMenuWhite: '白屏', paneShowMenuEnd: '结束放映',
}
export type TFunc = (key: string) => string
export const t: TFunc = key => messages[key] ?? key
