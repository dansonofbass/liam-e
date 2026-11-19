import { createContext, useContext, type ReactNode } from 'react'
import { catalogue } from './catalogue'
import { REFERENCE_LOCALE, intlLocale, type Locale } from './locales'

const languages = {
  de: { locale: 'de', localeTag: intlLocale.de, texts: catalogue('de') },
  en: { locale: 'en', localeTag: intlLocale.en, texts: catalogue('en') },
} as const

const LocaleContext = createContext<{ locale: Locale; browserLocale: Locale; ready: boolean } | undefined>(undefined)

export function I18nProvider({ locale, browserLocale = locale, ready = true, children }: { locale: Locale; browserLocale?: Locale; ready?: boolean; children: ReactNode }) {
  return <LocaleContext value={{ locale, browserLocale, ready }}>{children}</LocaleContext>
}

export function useActiveLocale() {
  return useContext(LocaleContext)?.locale
}

export function useI18n() {
  const current = useContext(LocaleContext)
  return { ...languages[current?.locale ?? REFERENCE_LOCALE], browserLocale: current?.browserLocale ?? REFERENCE_LOCALE, localeReady: current?.ready ?? true }
}
