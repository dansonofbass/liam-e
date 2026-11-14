import { IconButton, Menu } from '../ds'
import { de } from '../i18n/de'
import { setTheme, useTheme, type ThemeChoice } from './theme'

const choices: ThemeChoice[] = ['light', 'dark', 'system']
// Sits at the bottom of the sidebar, so its menu opens upwards: towards the content from the narrow tablet bar, inwards elsewhere.
export function ThemeMenu({ placement }: { placement: 'up-start' | 'up-end' }) {
  const theme = useTheme()
  return <Menu placement={placement} trigger={props => <IconButton {...props} label={de.shell.theme} tip={de.shell.themeTip} icon="sun-moon" />} items={choices.map(choice => ({ label: de.shell.themes[choice], checked: theme === choice, onSelect: () => setTheme(choice) }))} />
}
