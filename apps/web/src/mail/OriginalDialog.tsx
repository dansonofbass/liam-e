import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, apiErrorMessage, errorCode } from '../api/unwrap'
import { mailMessageOriginal } from '../api/generated/sdk.gen'
import { IconButton, Notice } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { useI18n } from '../i18n/I18n'

class OriginalRefusedError extends Error {
  constructor(readonly status: 404 | 409) { super() }
}

// Headers and source of one mail, fetched from the provider when the dialog opens and dropped when it closes.
export function OriginalDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { texts } = useI18n()
  const ref = useFocusTrap(true, onClose)
  const titleId = useId()
  const original = useQuery({
    queryKey: ['original', id], retry: false, staleTime: Infinity, gcTime: 0,
    queryFn: async () => {
      const result = await mailMessageOriginal({ path: { message_id: id } })
      // 404 and 409 are answers, not failures: a retry would get the same one.
      if (result.response?.status === 404) throw new OriginalRefusedError(404)
      if (result.response?.status === 409) throw new OriginalRefusedError(409)
      if (!result.data) throw new ApiError(result.error)
      return result.data
    },
  })
  const data = original.data
  const failure = original.error instanceof OriginalRefusedError
    ? original.error.status === 404 ? texts.proposalErrors.item_gone : texts.mail.originalRefused
    : errorCode(original.error) === 'provider_failed' ? texts.mail.originalError
    : apiErrorMessage(original.error, texts, texts.mail.originalError)
  // The retry button goes away while the original loads again; its focus would fall to the page behind the dialog.
  const retry = () => { ref.current?.focus(); void original.refetch() }
  // In the body, so the scrim also covers what stacks above the page (the sticky label in the sidebar).
  return createPortal(<div className="le-scrim" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><div className="le-dialog le-dialog--wide" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
    <div className="le-dialog-head"><h2 className="heading" id={titleId}>{texts.mail.originalTitle}</h2><IconButton label={texts.shell.close} icon="x" onClick={onClose} /></div>
    <div className="le-original-body" tabIndex={0}>
      {original.isPending && <p className="le-muted" role="status">{texts.mail.originalLoading}</p>}
      {original.isError && <Notice tone="danger" action={original.error instanceof OriginalRefusedError ? undefined : { label: texts.chat.retry, onClick: retry }}>{failure}</Notice>}
      {data && <>
        {data.truncated && <Notice tone="info">{texts.mail.originalTruncated}</Notice>}
        {data.headers.length > 0 && <section className="le-original-section"><h3 className="body-strong">{texts.mail.originalHeaders}</h3><dl className="le-original-headers small">{data.headers.map((header, index) => <div key={index}><dt>{header.name}</dt><dd>{header.value}</dd></div>)}</dl></section>}
        <section className="le-original-section"><h3 className="body-strong">{texts.mail.originalSource}</h3>{data.source ? <pre className="le-original-source small">{data.source}</pre> : <p className="le-muted">{texts.mail.originalEmpty}</p>}</section>
      </>}
    </div>
  </div></div>, document.body)
}
