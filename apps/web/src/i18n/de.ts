import { plural } from './format'

export const de = {
  shell: {
    chat: 'Chat', inbox: 'Posteingang', accounts: 'Konten', conversations: 'Unterhaltungen',
    newConversation: 'Neue Unterhaltung', openMenu: 'Menü öffnen', close: 'Schließen',
  },
  chat: {
    greeting: 'Hallo, was kann ich für dich tun?', placeholder: 'Frag etwas zu deinen Mails …',
    stopped: 'Angehalten – die Antwort ist unvollständig.', retry: 'Noch mal versuchen',
  },
  status: {
    thinking: 'Denke nach …',
    searching: (n: number) => `Durchsuche ${plural(n, { one: '# Konto', other: '# Konten' })} …`,
    reading: 'Lese Mails …',
    checking_deadlines: 'Prüfe Fristen …',
    finding_newsletters: 'Suche Newsletter …',
    preparing_proposal: 'Bereite einen Vorschlag vor …',
  },
  errors: {
    model_unavailable: 'Das Modell antwortet gerade nicht. Versuch es gleich noch mal.',
    aborted: 'Die Antwort ist abgebrochen.',
    internal: 'Die Antwort konnte nicht erstellt werden. Versuch es gleich noch mal.',
    auth_expired: 'Die Anmeldung ist abgelaufen. Melde dich erneut beim Anbieter an.',
    unreachable: 'Das Konto ist gerade nicht erreichbar. Versuch es gleich noch mal.',
    host_not_allowed: 'Der Server ist nicht erreichbar. Prüfe die Serveradresse.',
    provider_error: 'Der Anbieter antwortet gerade nicht. Versuch es gleich noch mal.',
    oauth_denied: 'Die Anmeldung wurde abgebrochen. Versuch es bei Bedarf noch mal.',
    oauth_state_invalid: 'Die Anmeldung ist abgelaufen. Starte sie erneut.',
    oauth_exchange_failed: 'Die Anmeldung beim Anbieter hat nicht geklappt. Versuch es erneut.',
    oauth_account_mismatch: 'Dieses Konto passt nicht. Melde dich mit dem ursprünglichen Konto an.',
    accountUnavailable: (name: string) => `${name} ist gerade nicht erreichbar. Die übrigen Konten arbeiten weiter.`,
  },
  inbox: { title: 'Posteingang' },
  mail: { summary: 'Kurz gefasst', draftReply: 'Antwort entwerfen', askInChat: 'Im Chat fragen' },
  accounts: { title: 'Konten', connect: 'Konto verbinden' },
  quickActions: {
    unread: { title: 'Ungelesenes zusammenfassen', subtitle: 'Ungelesene Mails ansehen', prompt: 'Fasse meine ungelesenen Mails zusammen.' },
    priority: { title: 'Priorisieren', subtitle: 'Wichtiges zuerst', prompt: 'Welche Mails sind wichtig?' },
    newsletters: { title: 'Newsletter aufräumen', subtitle: 'Newsletter durchsehen', prompt: 'Zeig mir meine Newsletter.' },
    dueToday: { title: 'Heute fällig', subtitle: 'Fristen im Blick', prompt: 'Was ist heute fällig?' },
  },
} as const
