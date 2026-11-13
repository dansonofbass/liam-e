import { expect, test } from 'bun:test'
import { de } from './de'

// Match complete words so that ordinary German words are not rejected as substrings.
const forbidden = /(?:\b(?:OK|Absenden|Account|Postfach|Inbox|Thread|Konversation|Session|Draft|Sync|Synchronisieren|Refresh|Ablegen|Verschieben|Abmelden|Unsubscribe|Hinzufügen|Einloggen|Login|Undo|Zurücknehmen|KI|LLM|Geheimnis|Token|Bot|Agent|Nachricht)\b|Chat-Verlauf|E-Mail\(s\)|Mail\(s\)|\.\.\.|!)/i // i18n-exempt

test('catalogue text follows the language guide', () => {
  function visit(value: unknown): void {
    if (typeof value === 'string') expect(value).not.toMatch(forbidden)
    else if (typeof value === 'function') visit(value(4))
    else if (value && typeof value === 'object') Object.values(value).forEach(visit)
  }
  visit(de)
})
