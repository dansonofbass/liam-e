import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { calendarSourceSync } from '../api/generated/sdk.gen'
import type { SourceOut } from '../api/generated/types.gen'
import { useI18n } from '../i18n/I18n'
import { calendarIndexCache } from './cache'

export function useCalendarRefresh(sources: SourceOut[] | undefined) {
  const client = useQueryClient()
  const { texts } = useI18n()
  const [refreshing, setRefreshing] = useState(false)
  const [notices, setNotices] = useState<Record<string, string>>({})

  useEffect(() => {
    for (const source of sources ?? []) {
      if (!source.is_active) continue
      // The server decides whether work is due. Share the last attempt across views and mounts.
      void client.fetchQuery({
        queryKey: ['calendar-due', source.id, source.revision],
        ...calendarIndexCache,
        retry: false,
        queryFn: async () => {
          await calendarSourceSync({ path: { source_id: source.id }, query: { due_only: true } })
          return true
        },
      }).catch(() => {}) // The worker also schedules due sources. Manual refresh reports failures.
    }
  }, [client, sources])

  const refresh = async (targets: SourceOut[]) => {
    setRefreshing(true)
    try {
      await Promise.all(targets.map(async source => {
        let message: string
        try {
          const result = await calendarSourceSync({ path: { source_id: source.id }, query: { due_only: false } })
          if (result.error || !result.response?.ok) throw new Error()
          message = result.data?.queued ? texts.calendar.queued
            : ['ics', 'google'].includes(source.provider) ? texts.calendar.feedNotQueued : texts.calendar.notQueued
        } catch { message = texts.calendar.refreshError }
        setNotices(current => ({ ...current, [source.id]: message }))
      }))
      const ids = new Set(targets.map(source => source.id))
      await client.invalidateQueries({ queryKey: ['calendar'], predicate: query =>
        query.queryKey[1] === 'sources'
        || (Array.isArray(query.meta?.calendarSourceIds) && query.meta.calendarSourceIds.some(id => ids.has(id))) })
    } finally { setRefreshing(false) }
  }
  return { refresh, refreshing, notices }
}
