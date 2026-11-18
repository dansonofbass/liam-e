import { useRestartConversation } from '../chat/session'
import { IconButton } from '../ds'
import { useI18n } from '../i18n/I18n'
export function MobileHeader({ title, conversationId, onMenu }: { title: string; conversationId?: string; onMenu: () => void }) {
  const { texts } = useI18n()
  const restart = useRestartConversation(conversationId)
  return <><IconButton label={texts.shell.openMenu} icon="menu" onClick={onMenu} /><span className="le-crumb le-crumb--center le-grow">{title}</span><IconButton label={texts.shell.newConversation} icon="plus" onClick={restart} /></>
}
