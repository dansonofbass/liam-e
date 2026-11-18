// i18n-exempt: API query keys.
import { queryOptions } from '@tanstack/react-query'
import { preferenceCandidatesList, preferencesList, settingsGet } from '../api/generated/sdk.gen'
import { unwrap } from '../api/unwrap'
export const preferencesQuery = () => queryOptions({ queryKey: ['preferences'], queryFn: () => unwrap(preferencesList({ throwOnError: true })) })
export const preferenceCandidatesQuery = (candidateId?: string) => queryOptions({ queryKey: ['preference-candidates', candidateId ?? 'all'], queryFn: () => unwrap(preferenceCandidatesList({ query: { candidate_id: candidateId }, throwOnError: true })) })
export const personalizationQuery = () => queryOptions({ queryKey: ['personalization'], queryFn: () => unwrap(settingsGet({ throwOnError: true })) })
