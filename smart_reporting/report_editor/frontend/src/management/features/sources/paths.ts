// 保留已合法存在的 new 标识，用独立详情地址避开创建页。
export const sourceDetailPath = (id: string) =>
  '/sources/' + encodeURIComponent(id) + (id === 'new' ? '/view' : '')
