import { IconButton, Menu } from '../ds'
import { useI18n } from '../i18n/I18n'
import { setTheme, useTheme, type ThemeChoice } from './theme'

const choices: ThemeChoice[] = ['light', 'dark', 'system']
// Sits at the bottom of the sidebar, so its menu opens upwards: towards the content from the narrow tablet bar, inwards elsewhere.
export function ThemeMenu({ placement }: { placement: 'up-start' | 'up-end' }) {
  const { texts } = useI18n()
  const theme = useTheme()
  return <Menu placement={placement} trigger={props => <IconButton {...props} label={texts.shell.theme} tip={texts.shell.themeTip} icon="sun-moon" />} items={choices.map(choice => ({ label: texts.shell.themes[choice], checked: theme === choice, onSelect: () => setTheme(choice) }))} />
}
