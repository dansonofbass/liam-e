import { useQuery } from '@tanstack/react-query'
import { audioCapabilitiesGet } from '../api/generated/sdk.gen'

export function useAudioCapabilities() {
  return useQuery({
    queryKey: ['audio', 'capabilities'],
    enabled: typeof window !== 'undefined',
    queryFn: async ({ signal }) => (await audioCapabilitiesGet({ signal })).data ?? null,
    retry: false,
    staleTime: 60_000,
  }).data
}
