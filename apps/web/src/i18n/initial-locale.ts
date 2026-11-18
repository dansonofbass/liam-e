import { createIsomorphicFn } from '@tanstack/react-start'
import { getCookie, getRequestHeader } from '@tanstack/react-start/server'
import { browserLocale, isLocale, LOCALE_COOKIE, requestLocale, type Locale } from './locales'

export type InitialLocales = { browser: Locale; page: Locale }

export const resolveInitialLocales = createIsomorphicFn()
  .server((): InitialLocales => {
    const browser = requestLocale(getRequestHeader('accept-language'))
    const cached = getCookie(LOCALE_COOKIE)
    return { browser, page: isLocale(cached) ? cached : browser }
  })
  .client((): InitialLocales => {
    const browser = browserLocale(navigator.languages.length ? navigator.languages : [navigator.language])
    return { browser, page: browser }
  })
