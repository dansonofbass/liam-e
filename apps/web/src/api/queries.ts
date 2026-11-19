import { infiniteQueryOptions, queryOptions, type QueryClient } from '@tanstack/react-query'
import { promptsList, promptGet, mailSummary, chatConversationsList, mailAccountsList, mailAccountOptions, mailConnectorsList, mailMessagesList, mailMessageGet, mailMessageInsight, chatHistory, chatModelsList, settingsUiGet, tasksGet, tasksList, tasksOccurrencesList, calendarSourcesList, calendarOccurrencesList, calendarOccurrenceGet } from './generated/sdk.gen'
import { REFERENCE_LOCALE, type Locale } from '../i18n/locales'
import type { MailMessagesListData, TasksGetData, TasksListData, TasksOccurrencesListData, UiSettingsOut } from './generated/types.gen'
import { dataOr404, unwrap } from './unwrap'

export class MessageNotFoundError extends Error {}

export const promptsQuery = () => queryOptions({ queryKey: ['prompts'], refetchOnWindowFocus: 'always', queryFn: () => unwrap(promptsList({ throwOnError: true })) })
export const promptQuery = (id: string) => queryOptions({ queryKey: ['prompts', id], refetchOnWindowFocus: 'always', queryFn: () => unwrap(promptGet({ path: { id }, throwOnError: true })) })

// Poll fast while an account syncs. While idle, keep a slow poll so syncs the worker schedules on
// its own (every few minutes) still refresh unread counts, the inbox and the sync time. Polling
// pauses while the tab is hidden; a refetch on window focus covers the return.
export const SUMMARY_SYNCING_POLL_MS = 3_000
export const SUMMARY_IDLE_POLL_MS = 60_000
export const summaryQuery = () => queryOptions({ queryKey: ['summary'], queryFn: () => unwrap(mailSummary({ throwOnError: true })), refetchInterval: query => !query.state.data ? false : query.state.data.accounts.some(a => a.state === 'syncing') ? SUMMARY_SYNCING_POLL_MS : SUMMARY_IDLE_POLL_MS })
export const conversationsQuery = () => queryOptions({ queryKey: ['conversations'], refetchOnWindowFocus: 'always', queryFn: () => unwrap(chatConversationsList({ throwOnError: true })) })
export const accountsQuery = () => queryOptions({ queryKey: ['accounts'], queryFn: () => unwrap(mailAccountsList({ throwOnError: true })) })
export const accountOptionsQuery = () => queryOptions({ queryKey: ['account-options'], queryFn: () => unwrap(mailAccountOptions({ throwOnError: true })) })
export const connectorsQuery = () => queryOptions({ queryKey: ['connectors'], queryFn: () => unwrap(mailConnectorsList({ throwOnError: true })) })
export const messagesInfiniteQuery = (filters: Omit<NonNullable<MailMessagesListData['query']>, 'cursor'>) => infiniteQueryOptions({ queryKey: ['messages', filters], initialPageParam: undefined as string | undefined, queryFn: ({ pageParam }) => unwrap(mailMessagesList({ query: { ...filters, cursor: pageParam }, throwOnError: true })), getNextPageParam: page => page.next_cursor ?? undefined })
export const messageQuery = (id: string) => queryOptions({ queryKey: ['message', id], queryFn: async () => dataOr404(await mailMessageGet({ path: { message_id: id } }), () => new MessageNotFoundError()) })
export const insightQuery = (id: string, locale: Locale = REFERENCE_LOCALE) => queryOptions({ queryKey: ['insight', id], queryFn: () => unwrap(mailMessageInsight({ path: { message_id: id }, query: { locale }, throwOnError: true })) })
export const historyQuery = (conversationId: string) => queryOptions({ queryKey: ['history', conversationId], queryFn: () => unwrap(chatHistory({ query: { conversation_id: conversationId }, throwOnError: true })) })
export const modelsQuery = () => queryOptions({ queryKey: ['models'], queryFn: () => unwrap(chatModelsList({ throwOnError: true })) })

// The confirmed device-independent UI settings; a second device reads the same row.
export const uiSettingsQuery = () => queryOptions({ queryKey: ['ui-settings'], refetchOnWindowFocus: 'always', queryFn: ({ signal }) => unwrap(settingsUiGet({ signal, throwOnError: true })) })

/** Apply a confirmed PATCH without allowing its delayed reply to roll back a newer language or swipe setting. */
export async function cacheUiSettings(client: QueryClient, saved: UiSettingsOut): Promise<UiSettingsOut> {
  const { queryKey } = uiSettingsQuery()
  await client.cancelQueries({ queryKey, exact: true })
  return client.setQueryData<UiSettingsOut>(queryKey, cached => cached && cached.revision > saved.revision ? cached : saved) ?? saved
}

// Task queries use their own scope; inbox filters never affect this data.
export const taskListQuery = (query: Omit<TasksListData['query'], 'cursor'>) => infiniteQueryOptions({ queryKey: ['tasks', 'list', query], initialPageParam: undefined as string | undefined, queryFn: ({ pageParam }) => unwrap(tasksList({ query: { ...query, cursor: pageParam }, throwOnError: true })), getNextPageParam: page => page.next_cursor ?? undefined })
export const taskOccurrencesQuery = (query: Omit<NonNullable<TasksOccurrencesListData['query']>, 'cursor'>) => infiniteQueryOptions({ queryKey: ['tasks', 'occurrences', query], initialPageParam: undefined as string | undefined, queryFn: ({ pageParam }) => unwrap(tasksOccurrencesList({ query: { ...query, cursor: pageParam }, throwOnError: true })), getNextPageParam: page => page.next_cursor ?? undefined })
export const taskDetailQuery = (id: string, query: Omit<TasksGetData['query'], 'cursor'>) => infiniteQueryOptions({ queryKey: ['tasks', 'detail', id, query], initialPageParam: undefined as string | undefined, queryFn: ({ pageParam }) => unwrap(tasksGet({ path: { series_id: id }, query: { ...query, cursor: pageParam }, throwOnError: true })), getNextPageParam: page => page.occurrences.next_cursor ?? undefined })

// Calendar reads use the index only; refreshes are explicit management operations.
export const calendarSourcesQuery = () => queryOptions({ queryKey: ['calendar', 'sources'], queryFn: () => unwrap(calendarSourcesList({ throwOnError: true })) })
export const calendarPageQuery = (from: string, to: string, source?: string, cursor?: string) => queryOptions({ queryKey: ['calendar', 'occurrences', from, to, source, cursor], queryFn: () => unwrap(calendarOccurrencesList({ query: { from, to, source_ids: source ? [source] : undefined, cursor, limit: 50 }, throwOnError: true })) })
export const calendarDetailQuery = (id: string) => queryOptions({ queryKey: ['calendar', 'occurrence', id], queryFn: () => unwrap(calendarOccurrenceGet({ path: { occurrence_id: id }, throwOnError: true })) })
import { queryWindows } from '../calendar/state'
export const calendarAgendaQuery = (from: string, to: string, timeZone: string, source?: string) => {
  const windows = queryWindows(from, to, timeZone)
  return infiniteQueryOptions({
    queryKey: ['calendar', 'agenda', from, to, timeZone, source],
    initialPageParam: { window: 0, cursor: undefined as string | undefined },
    queryFn: async ({ pageParam }) => {
      const window = windows[pageParam.window]
      if (!window) throw new Error('invalid calendar window')
      const page = await unwrap(calendarOccurrencesList({ query: { ...window, source_ids: source ? [source] : undefined, cursor: pageParam.cursor, limit: 50 }, throwOnError: true }))
      return { ...page, window: pageParam.window }
    },
    getNextPageParam: page => page.next_cursor ? { window: page.window, cursor: page.next_cursor } : page.window + 1 < windows.length ? { window: page.window + 1, cursor: undefined } : undefined,
  })
}
