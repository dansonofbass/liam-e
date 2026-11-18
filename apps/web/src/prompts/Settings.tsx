// i18n-exempt: route paths and CSS classes.
import { Link, Outlet } from '@tanstack/react-router'
import { de } from '../i18n/de'
import './prompts.css'

// Add implemented preferences and controls sections here; no placeholder destinations.
export const settingsSections = [{ to: '/settings/prompts', label: de.prompts.title }, { to: '/settings/controls', label: de.settingsUi.section }, { to: '/settings/preferences', label: de.preferences.title }] as const
export function Settings() {
  return <section className="le-settings"><h1 className="title">{de.prompts.settings}</h1><nav aria-label={de.prompts.settings}>{settingsSections.map(section => <Link key={section.to} to={section.to} className="le-btn le-btn--secondary">{section.label}</Link>)}</nav><Outlet /></section>
}
