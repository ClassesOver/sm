import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { detailSchema, pageSchema, sourceSchema } from '../../api/contracts'
import { scopeQuery, request } from '../../api/http'
import { keys } from '../../api/query-keys'
export type ScopeIdentity = { database: string; companyId: string }
export function useSource(scope: ScopeIdentity | null, id: string | undefined) {
  return useQuery({
    queryKey: keys.detail(
      scope?.database || '',
      scope?.companyId || '',
      id || '',
    ),
    enabled: !!scope && !!id,
    queryFn: ({ signal }) =>
      request(
        '/sources/' + encodeURIComponent(id!) + '?' + scopeQuery(scope!),
        detailSchema,
        { signal },
      ),
  })
}
export function useSources(
  scope: ScopeIdentity | null,
  q: string,
  status: string,
) {
  return useInfiniteQuery({
    queryKey: keys.sources(scope?.database || '', scope?.companyId || '', {
      q,
      status,
    }),
    enabled: !!scope,
    initialPageParam: '',
    queryFn: ({ pageParam, signal }) =>
      request(
        '/sources?' +
          scopeQuery(scope!) +
          '&' +
          new URLSearchParams({
            q,
            publicationState: status,
            limit: '50',
            ...(pageParam ? { after: pageParam } : {}),
          }),
        pageSchema(sourceSchema),
        { signal },
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
  })
}
