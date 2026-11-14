// Splits plain mail text into paragraphs at blank lines; a single line break stays inside its paragraph.
export function paragraphs(text: string): string[] {
  return text.replace(/\r\n?/gu, '\n').split(/\n(?:[^\S\n]*\n)+/u).map(part => part.replace(/^\n+|\s+$/gu, '')).filter(part => part !== '')
}
