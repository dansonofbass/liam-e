import { de } from '../i18n/de'

export function providerLabel(account: { provider: string; email_address: string }): string {
  const domain = account.email_address.split('@')[1] ?? ''
  const lower = domain.toLowerCase()
  return ['google', 'gmail', 'google_mail'].includes(account.provider) ? de.accountCard.providers.google : ['microsoft', 'outlook'].includes(account.provider) ? de.accountCard.providers.microsoft : account.provider === 'imap' ? ['icloud.com', 'me.com', 'mac.com'].includes(lower) ? de.accountCard.providers.icloud : ['yahoo.com', 'ymail.com', 'rocketmail.com'].includes(lower) ? de.accountCard.providers.yahoo : domain || account.email_address : account.provider
}
