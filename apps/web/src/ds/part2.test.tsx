import { afterEach, expect, mock, test } from 'bun:test'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { AccountOut, MessageListItemOut, ProposalItem, SendDraft } from '../api/generated/types.gen'
import { ConfirmCard } from './ConfirmCard'
import { MailRow } from './MailRow'
import { Composer } from './Composer'
import { AccountCard } from './AccountCard'

afterEach(cleanup)
const items: ProposalItem[] = ['a', 'b', 'c', 'd'].map(id => ({ id, kind: 'mail', title: id, subtitle: '' }))
const draft: SendDraft = { account_id: '1', body: 'Alt', cc: [], mode: 'new', quote: '', reply_to_message_id: null, subject: 'Betreff', to: ['max@example.org'] }
const mail: MessageListItemOut = { id: '1', account_id: '1', color_index: 0, deadline: '2026-11-21', has_attachments: true, internal_date: null, is_flagged: false, is_read: false, needs_reply: false, sender_address: 'a@example.org', sender_name: 'Anna', snippet: '', subject: 'Nebenkostenabrechnung 2025' }

test('confirmation uses selection count and edited draft', () => {
  const confirm = mock(() => {})
  const label = mock((n: number) => `${n} bestätigen`)
  render(<ConfirmCard title="Bestätigen?" reason="Grund" items={items} irreversibleNote="Nicht umkehrbar" confirmLabel={label} draft={draft} onConfirm={confirm} onCancel={() => {}} />)
  fireEvent.click(screen.getByLabelText('a'))
  expect(label).toHaveBeenLastCalledWith(3)
  expect(screen.getByText('Nicht umkehrbar')).toBeTruthy()
  fireEvent.change(screen.getByDisplayValue('Alt'), { target: { value: 'Neu' } })
  fireEvent.click(screen.getByRole('button', { name: '3 bestätigen' }))
  expect(confirm).toHaveBeenCalledWith(['b', 'c', 'd'], 'Neu')
  for (const id of ['b', 'c', 'd']) fireEvent.click(screen.getByLabelText(id))
  expect((screen.getByRole('button', { name: '0 bestätigen' }) as HTMLButtonElement).disabled).toBe(true)
})

test('confirm checkbox alignment and coarse mail reference targets', async () => {
  const css = await Bun.file(new URL('../styles/ds.css', import.meta.url)).text()
  const appCss = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  const nameRule = css.match(/\.le-confirm-item-name \{([^}]+)\}/u)?.[1]
  for (const property of ['display: inline-flex', 'align-items: center', 'gap: 12px']) expect(nameRule).toContain(property)
  const touchRule = appCss.match(/@media \(pointer: coarse\) \{ \.le-mailref-actions \.le-icon-btn, \.le-confirm-item label \{([^}]+)\} \}/u)?.[1]
  expect(touchRule).toContain('min-width: var(--control-height-lg)')
  expect(touchRule).toContain('min-height: var(--control-height-lg)')
  render(<ConfirmCard title="Bestätigen?" reason="Grund" items={items} confirmLabel={n => `${n} bestätigen`} onConfirm={() => {}} onCancel={() => {}} />)
  const name = screen.getByLabelText('a').closest('.le-confirm-item-name')
  expect(name?.querySelector('strong')?.textContent).toBe('a')
})

test('unread coarse mail exposes its actions and markers', () => {
  render(<MailRow mail={mail} selected={false} coarse onOpen={() => {}} onArchive={() => {}} onToggleRead={() => {}} onTrash={() => {}} />)
  expect(document.querySelector('.le-mailrow.is-unread')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen zu Nebenkostenabrechnung 2025' }))
  expect(screen.getByRole('menu')).toBeTruthy()
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Weitere Aktionen zu Nebenkostenabrechnung 2025' }))
  expect(document.querySelector('.le-tag--warm')).toBeTruthy()
  expect(document.querySelector('.lucide-paperclip')).toBeTruthy()
})

test('mail row menu stays in the right-hand time column', async () => {
  const css = await Bun.file(new URL('../styles/ds-app.css', import.meta.url)).text()
  expect(css).toMatch(/\.le-mailrow-side \{[^}]*grid-column: 3;/u)
  expect(css).toMatch(/\.le-mailrow-more \{[^}]*align-self: flex-end;/u)
  expect(css).toMatch(/@media \(max-width: 639px\), \(pointer: coarse\) \{[^\n]*\.le-mailrow-more \{ display: block; \}/u)
  render(<MailRow mail={{ ...mail, internal_date: '2026-11-13T08:00:00Z' }} selected={false} coarse onOpen={() => {}} onArchive={() => {}} onToggleRead={() => {}} onTrash={() => {}} />)
  const side = document.querySelector('.le-mailrow-side')!
  expect(side.querySelector('time')).toBeTruthy()
  expect(side.querySelector('.le-mailrow-more')?.contains(screen.getByRole('button', { name: 'Weitere Aktionen zu Nebenkostenabrechnung 2025' }))).toBe(true)
})

test('mail row shows a missing subject', () => {
  render(<MailRow mail={{ ...mail, subject: '' }} selected={false} coarse onOpen={() => {}} onArchive={() => {}} onToggleRead={() => {}} onTrash={() => {}} />)
  expect(screen.getByRole('button', { name: 'Ohne Betreff' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Weitere Aktionen zu Ohne Betreff' })).toBeTruthy()
})

test('composer submits on Enter and stops while busy', () => {
  const submit = mock(() => {}), stop = mock(() => {})
  const props = { value: 'Hallo', onChange: () => {}, onSubmit: submit, onStop: stop, scope: null, accounts: [{ id: '1', label: 'Privat' }], onScopeChange: () => {}, placeholder: 'Frage' }
  const { rerender } = render(<Composer {...props} busy={false} />)
  fireEvent.keyDown(screen.getByPlaceholderText('Frage'), { key: 'Enter', shiftKey: true })
  expect(submit).toHaveBeenCalledTimes(0)
  fireEvent.keyDown(screen.getByPlaceholderText('Frage'), { key: 'Enter' })
  expect(submit).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Alle Konten' }))
  expect(screen.getByRole('menuitem', { name: 'Privat' })).toBeTruthy()
  rerender(<Composer {...props} busy />)
  const button = screen.getByRole('button', { name: 'Anhalten' })
  expect(button.className).toContain('le-send--stop')
  fireEvent.click(button)
  expect(stop).toHaveBeenCalledTimes(1)
  rerender(<Composer {...props} value="" busy={false} />)
  expect((screen.getByRole('button', { name: 'Senden' }) as HTMLButtonElement).disabled).toBe(true)
})

test('IMAP account reports rejected password and missing secret', () => {
  const account: AccountOut = { id: '1', auth_type: 'imap_password', color_index: 0, connection: 'imap', created_at: '', display_name: 'Privat', email_address: 'a@example.org', error_code: 'auth_expired', is_active: true, last_sync_at: null, message_count: 1, provider: 'imap', state: 'auth_expired', unread: 0, updated_at: '' }
  const props = { onSync: () => {}, onReconnect: () => {}, onRename: () => {}, onRemove: () => {} }
  const { rerender } = render(<AccountCard account={account} {...props} />)
  expect(screen.getByText('Anmeldung abgelehnt')).toBeTruthy()
  expect(screen.getByText('Der Mailserver lehnt das App-Passwort ab. Prüfe das Secret in Mistral Studio.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Erneut anmelden' })).toBeTruthy()
  rerender(<AccountCard account={{ ...account, state: 'error', error_code: 'secret_not_found' }} {...props} />)
  expect(screen.getByText('Das Secret wurde nicht gefunden oder ist nicht lesbar. Prüfe den Namen und die Freigabe in Mistral Studio.')).toBeTruthy()
})

test('account status reflects syncing and login errors', () => {
  const account: AccountOut = { id: '1', auth_type: 'oauth2', color_index: 0, connection: 'oauth', created_at: '', display_name: 'Privat', email_address: 'a@example.org', error_code: '', is_active: true, last_sync_at: null, message_count: 1, provider: 'Gmail', state: 'syncing', unread: 0, updated_at: '' }
  const reconnect = mock(() => {})
  const props = { onSync: () => {}, onReconnect: reconnect, onRename: () => {}, onRemove: () => {} }
  const { rerender } = render(<AccountCard account={account} {...props} />)
  expect(screen.getByText('Wird abgerufen …')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Wird gerade abgerufen' }) as HTMLButtonElement).disabled).toBe(true)
  rerender(<AccountCard account={{ ...account, state: 'error', error_code: 'auth_expired' }} {...props} />)
  expect(screen.getByText('Die Anmeldung ist abgelaufen. Melde dich noch mal beim Anbieter an.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Erneut anmelden' }))
  expect(reconnect).toHaveBeenCalledTimes(1)
})
