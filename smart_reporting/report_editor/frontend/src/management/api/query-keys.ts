export const keys = {
  scopes: ['management', 'scopes'] as const,
  sources: (database: string, companyId: string, filters: unknown) =>
    ['management', 'sources', database, companyId, filters] as const,
  detail: (database: string, companyId: string, id: string) =>
    ['management', 'detail', database, companyId, id] as const,
}
