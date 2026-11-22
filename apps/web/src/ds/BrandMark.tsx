/**
 * The brand mark beside the name: the hyphenated "-e" from the app icon on the accent circle.
 * "liam-e" reads "e-mail" backwards; the mark is that "-e". It is decorative because the name
 * always stands next to it. The assistant keeps the `sparkle` mark (`le-ai-mark`); see DESIGN.md §6.
 */
export function BrandMark() {
  return <span className="le-mark" aria-hidden="true"><svg className="le-mark-glyph" viewBox="14 14 72 72" fill="none" stroke="currentColor" strokeWidth={7} strokeLinecap="round" strokeLinejoin="round"><path d="M22 50H78A21 21 0 1 0 72.6 64.05" /></svg></span>
}
