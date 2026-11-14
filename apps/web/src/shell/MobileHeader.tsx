import { useNavigate } from '@tanstack/react-router'
import { IconButton } from '../ds'
import { de } from '../i18n/de'
export function MobileHeader({ title, onMenu }: { title: string; onMenu: () => void }) {
  const navigate = useNavigate()
  return <><IconButton label={de.shell.openMenu} icon="menu" onClick={onMenu} /><span className="le-crumb le-crumb--center le-grow">{title}</span><IconButton label={de.shell.newConversation} icon="plus" onClick={() => void navigate({ to: '/' })} /></>
}
