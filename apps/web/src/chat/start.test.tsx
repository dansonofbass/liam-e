import { describe, expect, test } from 'bun:test'
import { de } from '../i18n/de'

describe('chat start', () => {
  test('quick action subtitles describe the available actions', () => {
    expect(de.quickActions.priority.subtitle).toBe('Was wartet auf dich?')
    expect(de.quickActions.unread.subtitle(1)).toBe('1 Mail')
    expect(de.quickActions.unread.subtitle(2)).toBe('2 Mails')
    expect(de.quickActions.newsletters.subtitle(2)).toBe('2 Absender')
    expect(de.quickActions.dueToday.subtitle).toBe('Fristen und Termine')
  })
})
