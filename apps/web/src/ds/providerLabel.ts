// i18n-exempt: provider names and domains.
export function providerLabel(account: { provider: string; email_address: string }): string {
  const domain = account.email_address.split('@')[1] ?? ''
  const lower = domain.toLowerCase()
  return ['google', 'gmail', 'google_mail'].includes(account.provider) ? 'Gmail' : ['microsoft', 'outlook'].includes(account.provider) ? 'Outlook' : account.provider === 'imap' ? ['icloud.com', 'me.com', 'mac.com'].includes(lower) ? 'iCloud' : ['yahoo.com', 'ymail.com', 'rocketmail.com'].includes(lower) ? 'Yahoo' : domain || account.email_address : account.provider
}
