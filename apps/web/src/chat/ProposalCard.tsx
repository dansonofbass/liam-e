import type { ChatMessageOut } from '../api/generated/types.gen'

// The confirmation flow is implemented separately.
export function ProposalCard({ message }: { message: ChatMessageOut }) {
  return <p>{message.proposal?.reason}</p>
}
