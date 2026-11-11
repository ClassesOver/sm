import { useInfiniteQuery } from '@tanstack/react-query'
import { request } from '../../api/http'
import { pageSchema, scopeSchema } from '../../api/contracts'
import { keys } from '../../api/query-keys'
export function useScopes() {
  return useInfiniteQuery({
    queryKey: keys.scopes,
    initialPageParam: '',
    queryFn: ({ pageParam, signal }) =>
      request(
        '/scopes?limit=50' +
          (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''),
        pageSchema(scopeSchema),
        { signal },
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
  })
}
