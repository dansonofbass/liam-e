import { expect, test } from 'bun:test'
import { isTimeZone } from './format'

test('time zones accept IANA names and reject offsets and free text', () => {
  for (const zone of ['Europe/Berlin', 'America/Argentina/Buenos_Aires', 'UTC', 'Etc/GMT+1']) expect(isTimeZone(zone)).toBe(true)
  for (const zone of ['', ' ', '+01:00', 'Invalid/Zone', 'Europe/', '../Berlin']) expect(isTimeZone(zone)).toBe(false)
})

test('time zones validate without Intl.supportedValuesOf', () => {
  const intl = Intl as { supportedValuesOf?: unknown }, original = intl.supportedValuesOf
  intl.supportedValuesOf = undefined
  try {
    expect(isTimeZone('Europe/Berlin')).toBe(true)
    expect(isTimeZone('Invalid/Zone')).toBe(false)
  } finally { intl.supportedValuesOf = original }
})
