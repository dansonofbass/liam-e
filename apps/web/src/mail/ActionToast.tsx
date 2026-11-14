import { Notice } from '../ds'
import { de } from '../i18n/de'
import { useMailActionsContext } from './useMailActions'

// Feedback of the shared mail actions. The list renders it as an overlay; the reading view
// renders it inline when it stands alone (mobile and tablet), since the list is unmounted there.
export function ActionToast({ inline }: { inline?: boolean }) {
  const { toast, undo } = useMailActionsContext()
  if (!toast) return null
  return <div className={inline ? 'le-inbox-toast le-inbox-toast--inline' : 'le-inbox-toast'}><Notice tone={toast.tone} action={toast.undoable ? { label: de.proposal.undo, onClick: () => { void undo() } } : undefined}><span>{toast.text}</span></Notice></div>
}
