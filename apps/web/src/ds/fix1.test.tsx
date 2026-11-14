import { afterEach, expect, test } from 'bun:test'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { MessageListItemOut } from '../api/generated/types.gen'
import { MailRow } from './MailRow'
import { MailReference } from './MailReference'
import { QuickAction } from './QuickAction'
import { formatTime } from '../i18n/format'

afterEach(cleanup)
const mail: MessageListItemOut = { id: '1', account_id: '1', color_index: 2, deadline: '2026-11-21', has_attachments: false, internal_date: null, is_flagged: false, is_read: false, needs_reply: false, sender_address: 'a@example.org', sender_name: 'Anna', snippet: '', subject: 'Betreff' }
const actions = { onOpen: () => {}, onArchive: () => {}, onToggleRead: () => {}, onTrash: () => {} }

test('mail row formats deadline and displays account tag', () => {
  render(<MailRow mail={mail} selected={false} coarse accountLabel="Privat" {...actions} />)
  expect(screen.getByText('Frist Sa., 21.11.')).toBeTruthy()
  expect(screen.getByText('Privat').className).toContain('le-tag--on-surface')
  expect(screen.getByText('Privat').querySelector('.le-dot--a3')).toBeTruthy()
})

test('mail reference formats deadline and displays account tag', () => {
  render(<MailReference mail={mail} accountLabel="Privat" onOpen={() => {}} />)
  expect(screen.getByText('Frist Sa., 21.11.')).toBeTruthy()
  expect(screen.getByText('Privat').className).toContain('le-tag--on-surface')
  expect(screen.getByText('Privat').querySelector('.le-dot--a3')).toBeTruthy()
})

test('mail row shows time for today', () => {
  const now = new Date()
  render(<MailRow mail={{ ...mail, internal_date: now.toISOString() }} selected={false} coarse {...actions} />)
  expect(screen.getByText(formatTime(now))).toBeTruthy()
})

test('quick action shows its tip on focus', () => {
  render(<QuickAction icon="inbox" title="Posteingang" sub="Mails" tip="Zeigt Mails" onClick={() => {}} />)
  fireEvent.focus(screen.getByRole('button'))
  expect(screen.getByRole('tooltip').textContent).toBe('Zeigt Mails')
})
