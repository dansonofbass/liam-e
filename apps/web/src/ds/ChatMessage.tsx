import type { ReactNode } from 'react'
import { useI18n } from '../i18n/I18n'
import { Icon } from './Icon'
export function ChatMessage({ role, model, streaming, stopped, live = true, children }: { role: 'user' | 'assistant'; model?: string; streaming?: boolean; stopped?: boolean; live?: boolean; children: ReactNode }) {
  const { texts } = useI18n()
  if (role === 'user') return <div className="le-msg-user le-rise">{children}</div>
  return <div className="le-msg-ai le-rise"><div className="le-ai-meta"><span className="le-ai-mark"><Icon name="sparkle" size="sm" /></span>{texts.assistant.name}{model && <small>{model}</small>}</div><div aria-live={live ? 'polite' : undefined} aria-busy={streaming || undefined}>{children}{streaming && <span className="le-caret" aria-hidden="true" />}</div>{stopped && <span className="le-hint">{texts.chat.stopped}</span>}</div>
}
