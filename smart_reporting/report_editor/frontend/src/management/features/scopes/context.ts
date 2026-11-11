import { useSearchParams } from 'react-router-dom'
export function useScope() {
  const [params] = useSearchParams()
  const database = params.get('database') || '',
    companyId = params.get('companyId') || ''
  return database && companyId ? { database, companyId } : null
}
export function scopeSuffix(
  scope: { database: string; companyId: string } | null,
) {
  return scope ? '?' + new URLSearchParams(scope) : ''
}
