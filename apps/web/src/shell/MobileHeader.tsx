import { useRestartConversation } from '../chat/session'
import { IconButton } from '../ds'
import { de } from '../i18n/de'
export function MobileHeader({ title, conversationId, onMenu }: { title: string; conversationId?: string; onMenu: () => void }) {
  const restart = useRestartConversation(conversationId)
  return <><IconButton label={de.shell.openMenu} icon="menu" onClick={onMenu} /><span className="le-crumb le-crumb--center le-grow">{title}</span><IconButton label={de.shell.newConversation} icon="plus" onClick={restart} /></>
}
