// i18n-exempt: API query keys.
import { queryOptions } from '@tanstack/react-query'
import { preferencesList, settingsGet } from '../api/generated/sdk.gen'
import { unwrap } from '../api/unwrap'
export const preferencesQuery = () => queryOptions({ queryKey: ['preferences'], queryFn: () => unwrap(preferencesList({ throwOnError: true })) })
export const personalizationQuery = () => queryOptions({ queryKey: ['personalization'], queryFn: () => unwrap(settingsGet({ throwOnError: true })) })
