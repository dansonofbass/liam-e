import { de } from '../i18n/de'
import type { RootScreens } from '../root-screens'

const screens: RootScreens = {
  resolveLocale: () => de.rootScreens.lang,
  texts: () => ({
    ...de.rootScreens,
    dir: 'ltr', // i18n-exempt
    starterHint: ({ file, directory }) => <>{de.rootScreens.starterHintBefore}{file}{de.rootScreens.starterHintBetween}{directory}{de.rootScreens.starterHintAfter}</>,
  }),
}

export default screens
