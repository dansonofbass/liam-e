import type { ReactNode } from 'react'
export function AppShell({ sidebar, header, children }: { sidebar: ReactNode; header?: ReactNode; children: ReactNode }) {
  return <div className="le-app"><aside className="le-side">{sidebar}</aside><main className="le-sheet">{header && <header className="le-topbar">{header}</header>}{children}</main></div>
}
