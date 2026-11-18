// i18n-exempt: route paths and CSS classes.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { promptsQuery } from '../api/queries'
import { Notice } from '../ds'
import { useI18n } from '../i18n/I18n'
import { formatListDate } from '../i18n/format'

export function Library() {
  const { texts, locale } = useI18n()
  const query = useQuery(promptsQuery())
  return <section className="le-prompts"><div className="le-prompt-actions"><h2 className="heading">{texts.prompts.title}</h2><Link className="le-btn le-btn--primary" to="/settings/prompts/new">{texts.prompts.create}</Link></div>
    {query.isPending && <><p role="status">{texts.prompts.loading}</p>{[0, 1, 2].map(i => <div key={i} className="le-prompt-placeholder" aria-hidden="true" />)}</>}
    {query.isError && <Notice tone="danger" action={{ label: texts.chat.retry, onClick: () => { void query.refetch() } }}>{texts.prompts.error}</Notice>}
    {query.data?.length === 0 && <p>{texts.prompts.empty}</p>}
    {query.data?.map(prompt => <Link className="le-prompt-row" key={prompt.id} to="/settings/prompts/$promptId" params={{ promptId: prompt.id }}><strong>{prompt.name}</strong><span className="le-prompt-preview">{prompt.text}</span><small>{texts.prompts.version(prompt.version)}{prompt.updated_at && <> · <time dateTime={prompt.updated_at}>{formatListDate(new Date(prompt.updated_at), new Date(), undefined, locale)}</time></>}</small></Link>)}
  </section>
}
