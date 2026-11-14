import { expect, test } from 'bun:test'
import { paragraphs } from './paragraphs'

test('splits at blank lines and keeps single line breaks inside a paragraph', () => {
  expect(paragraphs('Hallo\n\nzweiter Absatz\nmit Umbruch\n\nMit Gruß\nAnna')).toEqual(['Hallo', 'zweiter Absatz\nmit Umbruch', 'Mit Gruß\nAnna'])
})

test('treats runs of blank lines, whitespace-only lines and CRLF as one break', () => {
  expect(paragraphs('Eins\r\n\r\n\r\nZwei\n  \n\t\nDrei')).toEqual(['Eins', 'Zwei', 'Drei'])
})

test('drops empty edges but keeps indentation and quoted lines', () => {
  expect(paragraphs('\n\nHallo\n\n  > Zitat\n> weiter\n\n')).toEqual(['Hallo', '  > Zitat\n> weiter'])
  expect(paragraphs('')).toEqual([])
  expect(paragraphs(' \n \n ')).toEqual([])
})
