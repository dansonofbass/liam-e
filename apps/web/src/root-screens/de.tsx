import { Link } from '@tanstack/react-router'
import { Button } from '../ds'
import { de } from '../i18n/de'
import type { RootScreens } from '../root-screens'

// The error and not-found screens in the app's own look, so no screen falls back to raw controls and Tailwind sizes (DESIGN.md §6).
const screens: RootScreens = {
  resolveLocale: () => de.rootScreens.lang,
  texts: () => ({
    ...de.rootScreens,
    dir: 'ltr', // i18n-exempt
    starterHint: ({ file, directory }) => <>{de.rootScreens.starterHintBefore}{file}{de.rootScreens.starterHintBetween}{directory}{de.rootScreens.starterHintAfter}</>,
  }),
  MissingChunk: ({ texts, onReload }) => <main className="le-root-screen"><h1 className="heading">{texts.missingChunkTitle}</h1><p>{texts.missingChunk}</p><Button variant="primary" icon="refresh-cw" onClick={onReload}>{texts.reload}</Button></main>,
  ErrorScreen: ({ texts, message, onRetry }) => <main className="le-root-screen"><h1 className="heading">{texts.errorTitle}</h1><p>{texts.errorDescription}</p><Button variant="primary" icon="refresh-cw" onClick={onRetry}>{texts.retry}</Button><details className="small le-muted"><summary>{texts.errorDetails}</summary>{/* The error's own words, in whatever language it was thrown in. */}<pre dir="auto">{message}</pre></details></main>,
  NotFound: ({ texts }) => <main className="le-root-screen"><h1 className="heading">{texts.notFound}</h1><p>{texts.notFoundDescription}</p><Link to="/" className="le-link">{texts.home}</Link></main>,
}

export default screens
