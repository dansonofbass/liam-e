import type { ChatModelOut } from '../api/generated/types.gen'
import type { MenuItem } from '../ds/Menu'
import type { Catalogue } from '../i18n/catalogue'

export function modelMenuItems(models: ChatModelOut[], selected: string | undefined, unavailable: boolean,
  texts: Catalogue['chat'], locale: string, select: (id: string) => void, refresh: () => void) {
  const order = ['current', 'recommended', 'general', 'specialist', 'third_party', 'other'] as const
  const buckets = new Map<string, MenuItem[]>()
  const actions: MenuItem[] = []
  const descriptions: Partial<Record<string, string>> = texts.modelDescriptions
  // A previously saved version may now be listed under a moving alias.
  // Keep the exact version as its own checked choice when the user opens it.
  if (selected && !models.some(model => model.id === selected)) {
    const alias = models.find(model => model.resolved_id === selected)
    if (alias) models = [...models, { ...alias, id: selected, label: selected, is_default: false, recommended: false }]
  }
  for (const model of models) {
    if (unavailable || model.availability === 'unlisted' || model.availability === 'unverified') continue
    const group = model.recommended ? 'recommended' : model.group ?? 'other'
    const items = buckets.get(group) ?? []
    const description = model.recommended ? texts.modelMailReason : descriptions[model.id] ?? model.description
    const version = model.resolved_id && model.resolved_id !== model.id ? `${model.id} → ${model.resolved_id}` : model.label !== model.id ? model.id : ''
    let cost = !model.resolved_id && model.id.endsWith('-latest') ? texts.modelAliasUnresolved : texts.modelPriceUnknown
    if (model.price) {
      const { currency = 'USD', input_per_million, output_per_million, source, checked_on } = model.price
      const format = new Intl.NumberFormat(locale, { style: 'currency', currency, currencyDisplay: 'code' })
      cost = texts.modelPrices(format.format(input_per_million), format.format(output_per_million))
      if (!actions.some(action => action.href === source)) {
        const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(checked_on))
        const label = source.includes('/models/') ? texts.modelCardSource(model.resolved_id ?? model.id, date) : texts.modelPriceSource(date)
        actions.push({ label, href: source, hint: texts.modelPriceTerms })
      }
    }
    items.push({ label: model.label, hint: [description, cost, version].filter(Boolean).join('\n'), checked: model.id === selected, onSelect: () => select(model.id) })
    buckets.set(group, items)
  }
  const current = models.find(model => model.id === selected)
  if (selected && (unavailable || !current || current.availability === 'unlisted' || current.availability === 'unverified')) {
    buckets.set('current', [{ label: selected, checked: true, disabled: true, hint: unavailable ? texts.modelUnverified : texts.modelUnlisted, onSelect: () => {} }])
  }
  if (unavailable || !buckets.size || (buckets.size === 1 && buckets.has('current'))) {
    actions.unshift({ label: texts.modelRefresh, hint: unavailable ? texts.modelUnverified : texts.modelUnlisted, onSelect: refresh })
  }
  const groups = order.flatMap(key => {
    const items = buckets.get(key)
    return items ? [{ label: texts.modelGroups[key], items }] : []
  })
  return { groups, items: actions }
}
