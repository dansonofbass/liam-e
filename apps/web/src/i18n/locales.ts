import type { UiSettingsOut } from '../api/generated/types.gen'

/** Used when none of the browser's preferred languages are supported. */
export const FALLBACK_LOCALE = 'en'
/** The source language for copy and standalone formatting helpers. */
export const REFERENCE_LOCALE = 'de'

export type LocalePreference = UiSettingsOut['locale']
export type Locale = Exclude<LocalePreference, 'browser'>

export const intlLocale = { de: 'de-DE', en: 'en-US' } satisfies Record<Locale, string>
export const LOCALE_COOKIE = 'liam-e-ui-locale'

export function isLocale(value: unknown): value is Locale {
  return value === 'de' || value === 'en'
}

export function browserLocale(languages: readonly string[]): Locale {
  for (const language of languages) {
    const code = language.trim().toLowerCase().split('-')[0]
    if (isLocale(code)) return code
  }
  return FALLBACK_LOCALE
}

export function requestLocale(header: string | undefined): Locale {
  const languages = (header ?? '').split(',').map(value => {
    const [language = '', weight] = value.trim().split(';').map(part => part.trim())
    return { language, weight: weight === undefined ? 1 : /^q=(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$/i.test(weight) ? Number(weight.slice(2)) : 0 }
  })
  return browserLocale(languages.filter(item => item.weight > 0).sort((a, b) => b.weight - a.weight).map(item => item.language))
}
