import { REFERENCE_LOCALE, intlLocale, type Locale } from './locales'

export function plural(n: number, forms: { zero?: string; one: string; other: string }, locale: Locale = REFERENCE_LOCALE): string {
  const language = intlLocale[locale]
  const form = n === 0 && forms.zero !== undefined ? forms.zero : new Intl.PluralRules(language).select(n) === 'one' ? forms.one : forms.other
  return form.replaceAll('#', new Intl.NumberFormat(language).format(n))
}
