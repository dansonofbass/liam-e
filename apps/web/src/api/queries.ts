import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'
import { promptsList, promptGet, mailSummary, chatConversationsList, mailAccountsList, mailAccountOptions, mailConnectorsList, mailMessagesList, mailMessageGet, mailMessageInsight, chatHistory, chatModelsList } from './generated/sdk.gen'
import type { MailMessagesListData } from './generated/types.gen'
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
export const insightQuery = (id: string) => queryOptions({ queryKey: ['insight', id], queryFn: () => unwrap(mailMessageInsight({ path: { message_id: id }, throwOnError: true })) })
export const historyQuery = (conversationId: string) => queryOptions({ queryKey: ['history', conversationId], queryFn: () => unwrap(chatHistory({ query: { conversation_id: conversationId }, throwOnError: true })) })
export const modelsQuery = () => queryOptions({ queryKey: ['models'], queryFn: () => unwrap(chatModelsList({ throwOnError: true })) })
