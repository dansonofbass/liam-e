// i18n-exempt: CSS classes.
import { useId } from 'react'
import { Chip, Icon, Menu } from '../ds'

export function TaskSelect({ label, value, options, onChange, fallback }: { label: string; value: string; options: { value: string; label: string }[]; onChange: (value: string) => void; fallback?: string }) {
  const id = useId()
  const selected = options.find(option => option.value === value)
  return <div className="le-field"><span className="le-label" id={id}>{label}</span>
    <Menu trigger={props => <Chip {...props} quiet aria-labelledby={id}>{selected?.label ?? fallback ?? value}<Icon name="chevron-down" size="sm" /></Chip>}
      items={options.map(option => ({ label: option.label, checked: option.value === value, onSelect: () => onChange(option.value) }))} />
  </div>
}
