import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { mailAccountOauthAuthorize, mailAccountSync, mailAccountUpdate, mailSyncAll } from '../api/generated/sdk.gen'
import type { AccountOut } from '../api/generated/types.gen'
import { accountsQuery } from '../api/queries'
import { errorCode } from '../api/unwrap'
import { AccountCard, Button, Notice, Tooltip } from '../ds'
import { de } from '../i18n/de'
import { useBreakpoint, useCoarsePointer } from '../shell/useBreakpoint'
import { redirect } from './redirect'
import { RemoveDialog } from './RemoveDialog'
import { ConnectPanel } from './ConnectPanel'

const messageFor = (error: unknown, fallback: string) => {
  const code = errorCode(error)
  const text = code ? (de.errors as Record<string, unknown>)[code] : undefined
  return typeof text === 'string' ? text : fallback
}
type PageNotice = { tone: 'success' | 'info' | 'danger'; text: string }
export function AccountsPage() {
  const client = useQueryClient(), navigate = useNavigate(), breakpoint = useBreakpoint(), coarse = useCoarsePointer()
  const search = useSearch({ strict: false }) as { connected?: string; error?: string }
  const accounts = useQuery({ ...accountsQuery(), refetchInterval: query => query.state.data?.some(a => a.state === 'syncing') ? 3000 : false })
  const [notice, setNotice] = useState<PageNotice>()
  const [pending, setPending] = useState<string[]>([]), [allPending, setAllPending] = useState(false)
  const handled = useRef(new Set<string>())
  const [removing, setRemoving] = useState<AccountOut>()
  const [imapReconnect, setImapReconnect] = useState<{ address: string; sequence: number }>()
  const [focusAfterRemove, setFocusAfterRemove] = useState(false)
  const listHeading = useRef<HTMLHeadingElement>(null), connectHeading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (!focusAfterRemove) return
    ;(accounts.data?.length ? listHeading.current : connectHeading.current)?.focus()
    setFocusAfterRemove(false)
  }, [focusAfterRemove, accounts.data])
  const invalidate = () => { void client.invalidateQueries({ queryKey: ['accounts'] }); void client.invalidateQueries({ queryKey: ['summary'] }) }
  const sync = async (id: string) => {
    setPending(current => [...current, id])
    try {
      const result = await mailAccountSync({ path: { account_id: id } })
      if (result.error || !result.response?.ok) throw result.error
      invalidate()
    } catch (error) { setNotice({ tone: 'danger', text: messageFor(error, de.accounts.actionError) }) } finally { setPending(current => current.filter(item => item !== id)) }
  }
  useEffect(() => {
    const key = search.connected ? `connected:${search.connected}` : search.error ? `error:${search.error}` : undefined
    if (!key || handled.current.has(key)) return
    handled.current.add(key)
    if (search.connected) { setNotice({ tone: 'success', text: de.accounts.connected }); void sync(search.connected) }
    else if (search.error) setNotice({ tone: 'danger', text: messageFor({ detail: { code: search.error } }, de.accounts.returnError) })
    void navigate({ to: '/accounts', search: {}, replace: true })
  }, [search.connected, search.error, navigate])
  const refreshAll = async () => {
    setAllPending(true)
    try { const result = await mailSyncAll({ body: {} }); if (result.error || !result.response?.ok) throw result.error; invalidate() }
    catch { setNotice({ tone: 'danger', text: de.inbox.refreshError }) } finally { setAllPending(false) }
  }
  const reconnect = async (account: AccountOut) => {
    if (account.connection === 'connector') { setNotice({ tone: 'info', text: de.accounts.connectorNotice }); return }
    if (account.connection === 'imap') { setImapReconnect(previous => ({ address: account.email_address, sequence: (previous?.sequence ?? 0) + 1 })); return }
    if (account.provider !== 'google' && account.provider !== 'microsoft') { setNotice({ tone: 'danger', text: de.accounts.actionError }); return }
    try {
      const result = await mailAccountOauthAuthorize({ path: { provider: account.provider }, query: { account_id: account.id } })
      if (result.error || !result.data) throw result.error
      redirect.to(result.data.authorization_url)
    } catch (error) { setNotice({ tone: 'danger', text: messageFor(error, de.accounts.actionError) }) }
  }
  const rename = async (account: AccountOut, name: string): Promise<string | undefined> => {
    try {
      const result = await mailAccountUpdate({ path: { account_id: account.id }, body: { display_name: name } })
      if (result.error || !result.data) throw result.error
      const updated = result.data
      client.setQueryData<AccountOut[]>(['accounts'], current => current?.map(item => item.id === account.id ? updated : item))
      void client.invalidateQueries({ queryKey: ['summary'] })
      return undefined
    } catch (error) { return messageFor(error, de.accounts.actionError) }
  }
  const removed = (account: AccountOut) => {
    client.setQueryData<AccountOut[]>(['accounts'], current => current?.filter(item => item.id !== account.id))
    void client.invalidateQueries({ queryKey: ['summary'] }); void client.invalidateQueries({ queryKey: ['messages'] })
    setRemoving(undefined); setNotice({ tone: 'success', text: de.accounts.removed(account.display_name || account.email_address) }); setFocusAfterRemove(true)
  }
  const refreshButton = accounts.data?.length ? <Tooltip content={de.accounts.refreshAllTip}><Button variant="ghost" icon="refresh-cw" className="le-btn--sm le-accounts-refresh" disabled={allPending} onClick={() => { void refreshAll() }}>{de.accounts.refreshAll}</Button></Tooltip> : null
  return <>
    {breakpoint !== 'mobile' ? <div className="le-topbar"><h1 className="le-crumb">{de.accounts.title}</h1><span className="le-grow" />{refreshButton}</div> : <div className="le-inbox-mobile-status"><span className="le-grow" />{refreshButton}</div>}
    <div className="le-accounts-scroll">{notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {accounts.isError && !accounts.data && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void accounts.refetch() } }}>{de.accounts.loadError}</Notice>}
      {accounts.data?.length === 0 && <p className="le-hint">{de.accounts.empty}</p>}
      <div className="le-accounts-layout">
        {(accounts.isPending || Boolean(accounts.data?.length)) && <section className="le-accounts-list"><h2 className="heading" id="accounts-heading" ref={listHeading} tabIndex={-1}>{de.accounts.connectedAccounts}</h2>
          {accounts.isPending ? <><span className="le-sr" role="status">{de.accounts.loading}</span><div aria-hidden="true">{Array.from({ length: 3 }, (_, i) => <div className="le-account le-account--placeholder" key={i}><span /><span /></div>)}</div></> : <ul aria-labelledby="accounts-heading">{accounts.data?.map(account => <li key={account.id}><AccountCard account={account} coarse={coarse} syncPending={pending.includes(account.id)} onSync={() => { void sync(account.id) }} onReconnect={() => { void reconnect(account) }} onRename={() => {}} onSaveName={name => rename(account, name)} onRemove={() => setRemoving(account)} /></li>)}</ul>}
          {Boolean(accounts.data?.length) && <small className="le-muted">{de.accounts.removeFootnote}</small>}
        </section>}
        <ConnectPanel headingRef={connectHeading} reconnect={imapReconnect} onConnected={account => { setNotice({ tone: 'success', text: de.accounts.connected }); invalidate(); void sync(account.id) }} />
      </div>
    </div>
    {removing && <RemoveDialog account={removing} onClose={() => setRemoving(undefined)} onRemoved={() => removed(removing)} />}
  </>
}
