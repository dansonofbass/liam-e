import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { createPortal } from 'react-dom'
import { mailMessageOriginal } from '../api/generated/sdk.gen'
import { IconButton, Notice } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { de } from '../i18n/de'

class OriginalRefusedError extends Error {}

// Headers and source of one mail, fetched from the provider when the dialog opens and dropped when it closes.
export function OriginalDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const ref = useFocusTrap(true, onClose)
  const titleId = useId()
  const original = useQuery({
    queryKey: ['original', id], retry: false, staleTime: Infinity, gcTime: 0,
    queryFn: async () => {
      const result = await mailMessageOriginal({ path: { message_id: id } })
      // 404 and 409 are answers, not failures: a retry would get the same one.
      if (result.response?.status === 404) throw new OriginalRefusedError(de.proposalErrors.item_gone)
      if (result.response?.status === 409) throw new OriginalRefusedError(de.mail.originalRefused)
      if (!result.data) throw new Error(de.mail.originalError)
      return result.data
    },
  })
  const data = original.data
  // In the body, so the scrim also covers what stacks above the page (the sticky label in the sidebar).
  return createPortal(<div className="le-scrim" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><div className="le-dialog le-dialog--wide" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
    <div className="le-dialog-head"><h2 className="heading" id={titleId}>{de.mail.originalTitle}</h2><IconButton label={de.shell.close} icon="x" onClick={onClose} /></div>
    <div className="le-original-body" tabIndex={0}>
      {original.isPending && <p className="le-muted" role="status">{de.mail.originalLoading}</p>}
      {original.isError && <Notice tone="danger" action={original.error instanceof OriginalRefusedError ? undefined : { label: de.chat.retry, onClick: () => { void original.refetch() } }}>{original.error.message}</Notice>}
      {data && <>
        {data.truncated && <Notice tone="info">{de.mail.originalTruncated}</Notice>}
        {data.headers.length > 0 && <section className="le-original-section"><h3 className="body-strong">{de.mail.originalHeaders}</h3><dl className="le-original-headers small">{data.headers.map((header, index) => <div key={index}><dt>{header.name}</dt><dd>{header.value}</dd></div>)}</dl></section>}
        <section className="le-original-section"><h3 className="body-strong">{de.mail.originalSource}</h3>{data.source ? <pre className="le-original-source small">{data.source}</pre> : <p className="le-muted">{de.mail.originalEmpty}</p>}</section>
      </>}
    </div>
  </div></div>, document.body)
}
