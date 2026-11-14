import Markdown from 'react-markdown'

export function SafeMarkdown({ text }: { text: string }) {
  return <Markdown skipHtml disallowedElements={['img']} unwrapDisallowed urlTransform={url => {
    const trimmed = url.trim()
    return /^(?:https?:|mailto:)/iu.test(trimmed) ? trimmed : null
  }} components={{
    a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
    p: ({ node: _node, ...props }) => <p {...props} className="le-answer-p" />,
    h1: ({ node: _node, ...props }) => <h1 {...props} className="le-answer-h" />,
    h2: ({ node: _node, ...props }) => <h2 {...props} className="le-answer-h" />,
    h3: ({ node: _node, ...props }) => <h3 {...props} className="le-answer-h" />,
  }}>{text}</Markdown>
}
