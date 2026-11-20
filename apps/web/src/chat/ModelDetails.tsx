import { useId } from 'react'
import { createPortal } from 'react-dom'
import type { ChatModelOut } from '../api/generated/types.gen'
import { IconButton, Notice } from '../ds'
import { useFocusTrap } from '../ds/useFocusTrap'
import { useI18n } from '../i18n/I18n'

export function ModelDetails({ models, unavailable, onRefresh, onClose }: {
  models: ChatModelOut[]
  unavailable: boolean
  onRefresh: () => void
  onClose: () => void
}) {
  const { texts, localeTag } = useI18n()
  const copy = texts.chat
  const descriptions: Partial<Record<string, string>> = copy.modelDescriptions
  const ref = useFocusTrap(true, onClose)
  const title = useId()
  const date = new Intl.DateTimeFormat(localeTag, { dateStyle: 'medium', timeZone: 'UTC' })
  return createPortal(<div className="le-scrim" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <div className="le-dialog" role="dialog" aria-modal="true" aria-labelledby={title} tabIndex={-1} ref={ref}>
      <div className="le-dialog-head"><h2 id={title} className="heading">{copy.modelDetails}</h2><IconButton label={texts.shell.close} icon="x" onClick={onClose} /></div>
      {!models.length && <Notice tone="info" action={{ label: copy.modelRefresh, onClick: onRefresh }}>{unavailable ? copy.modelUnverified : copy.noMailModels}</Notice>}
      {models.map(model => {
        const description = model.recommended ? copy.modelMailReason : descriptions[model.id] ?? model.description
        const price = model.price
        const rate = price && new Intl.NumberFormat(localeTag, { style: 'currency', currency: price.currency ?? 'USD', currencyDisplay: 'code' })
        const version = model.resolved_id && model.resolved_id !== model.id ? `${model.id} → ${model.resolved_id}` : model.id
        return <section className="le-model-detail" key={model.id}>
          <h3 className="body-strong">{model.label}</h3>
          {version !== model.label && <small className="le-muted">{version}</small>}
          {description && <p>{description}</p>}
          {price && rate ? <>
            <p>{copy.modelPrices(rate.format(price.input_per_million), rate.format(price.output_per_million))}</p>
            <a className="le-link" href={price.source} target="_blank" rel="noreferrer">{price.source.includes('/models/')
              ? copy.modelCardSource(model.resolved_id ?? model.id, date.format(new Date(price.checked_on)))
              : copy.modelPriceSource(date.format(new Date(price.checked_on)))}</a>
          </> : <p>{!model.resolved_id && model.id.endsWith('-latest') ? copy.modelAliasUnresolved : copy.modelPriceUnknown}</p>}
        </section>
      })}
      {models.some(model => model.price) && <p className="le-hint">{copy.modelPriceTerms}</p>}
    </div>
  </div>, document.body)
}
