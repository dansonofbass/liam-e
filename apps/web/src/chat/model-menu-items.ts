import type { ChatModelOut } from '../api/generated/types.gen'
import type { MenuItem } from '../ds/Menu'
import type { Catalogue } from '../i18n/catalogue'

export function modelMenuItems(models: ChatModelOut[], selected: string | undefined, unavailable: boolean,
  texts: Catalogue['chat'], select: (id: string) => void, refresh: () => void, showDetails: () => void) {
  // A previously saved version may now be listed under a moving alias.
  // Keep the exact version as its own checked choice when the user opens it.
  if (selected && !models.some(model => model.id === selected)) {
    const alias = models.find(model => model.resolved_id === selected)
    if (alias) models = [...models, { ...alias, id: selected, label: selected, is_default: false, recommended: false }]
  }
  const priority = (model: ChatModelOut) => {
    if (model.id === selected) return 3
    if (model.recommended) return 2
    return model.is_default ? 1 : 0
  }
  const choices = new Map<string, ChatModelOut>()
  for (const model of models) {
    if (unavailable) break
    if (model.group !== 'general' || model.availability === 'unlisted' || model.availability === 'unverified') continue
    const key = model.resolved_id ?? model.id
    const previous = choices.get(key)
    // One row per verified version. Keep the actual selected ID, then the
    // recommendation or configured default, when equivalent aliases exist.
    const choice = !previous || priority(model) > priority(previous) ? model : previous
    choices.set(key, previous?.recommended || model.recommended ? { ...choice, recommended: true } : choice)
  }
  const details = [...choices.values()].sort((a, b) => Number(!!b.recommended) - Number(!!a.recommended))
  const labelCounts = new Map<string, number>()
  for (const { label } of details) labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1)
  const items: MenuItem[] = details.map(model => ({
    label: model.recommended ? texts.modelRecommended(model.label) : model.label,
    hint: labelCounts.get(model.label)! > 1 ? model.resolved_id ?? model.id : undefined,
    checked: model.id === selected,
    onSelect: () => select(model.id),
  }))
  const current = models.find(model => model.id === selected)
  if (selected && (unavailable || !current || current.availability === 'unlisted' || current.availability === 'unverified' || current.group !== 'general')) {
    const hint = unavailable || current?.availability === 'unverified' ? texts.modelUnverified
      : !current || current.availability === 'unlisted' ? texts.modelUnlisted : texts.modelOutsideMail
    items.unshift({ label: selected, checked: true, disabled: true, hint, onSelect: () => {} })
  }
  if (details.length) items.push({ label: texts.modelDetails, icon: 'info', onSelect: showDetails })
  else items.push({ label: texts.modelRefresh, hint: unavailable ? texts.modelUnverified : texts.noMailModels, onSelect: refresh })
  return { items, details }
}
