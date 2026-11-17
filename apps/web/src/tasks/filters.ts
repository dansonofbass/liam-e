// URL values are optional so default filters are omitted when navigating.
export type TaskSearch = { status?: 'completed' | 'archived'; source?: 'unlinked' | 'account'; source_account_id?: string }

export function taskSearchSchema(search: Record<string, unknown>): TaskSearch {
  const status = search.status === 'completed' || search.status === 'archived' ? search.status : undefined
  const accountId = typeof search.source_account_id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(search.source_account_id) ? search.source_account_id : undefined
  const source = search.source === 'unlinked' ? 'unlinked' : search.source === 'account' && accountId ? 'account' : undefined
  return { status, source, source_account_id: source === 'account' ? accountId : undefined }
}
