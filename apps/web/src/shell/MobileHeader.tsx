import { useRestartConversation } from '../chat/session'
import { createContext, type Ref } from 'react'
import { IconButton } from '../ds'
import { useI18n } from '../i18n/I18n'
export const MobileModelSlot = createContext<HTMLSpanElement | null>(null)

export function MobileHeader({ title, conversationId, onMenu, modelSlotRef }: { title: string; conversationId?: string; onMenu: () => void; modelSlotRef?: Ref<HTMLSpanElement> }) {
  const { texts } = useI18n()
  const restart = useRestartConversation(conversationId)
  return <><IconButton label={texts.shell.openMenu} icon="menu" onClick={onMenu} /><span className="le-crumb le-crumb--center le-grow">{title}</span>{modelSlotRef && <span className="le-mobile-model" ref={modelSlotRef} />}<IconButton label={texts.shell.newConversation} icon="plus" onClick={restart} /></>
}
