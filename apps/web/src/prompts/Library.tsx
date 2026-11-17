// i18n-exempt: route paths and CSS classes.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { promptsQuery } from '../api/queries'
import { Notice } from '../ds'
import { de } from '../i18n/de'

export function Library() {
  const query = useQuery(promptsQuery())
  return <section className="le-prompts"><div className="le-prompt-actions"><h2 className="heading">{de.prompts.title}</h2><Link className="le-btn le-btn--primary" to="/settings/prompts/new">{de.prompts.create}</Link></div>
    {query.isPending && <><p role="status">{de.prompts.loading}</p>{[0, 1, 2].map(i => <div key={i} className="le-prompt-placeholder" aria-hidden="true" />)}</>}
    {query.isError && <Notice tone="danger" action={{ label: de.chat.retry, onClick: () => { void query.refetch() } }}>{de.prompts.error}</Notice>}
    {query.data?.length === 0 && <p>{de.prompts.empty}</p>}
    {query.data?.map(prompt => <Link className="le-prompt-row" key={prompt.id} to="/settings/prompts/$promptId" params={{ promptId: prompt.id }}><strong>{prompt.name}</strong><span className="le-prompt-preview">{prompt.text}</span><small>{de.prompts.version(prompt.version)}</small></Link>)}
  </section>
}
