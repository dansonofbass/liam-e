"""Check maintained Markdown links and documented paths in tracked source files."""

import io
import re
import subprocess
import tokenize
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
DOC_PATH = re.compile(r"(?<![\w/])docs/[\w./-]+\.md")
DESIGN_SECTION = re.compile(r'DESIGN\.md\s+§(\d+(?:\.\d+)*)')


def tracked(*patterns: str) -> list[Path]:
    output = subprocess.check_output(['git', 'ls-files', '-z', '--', *patterns], cwd=ROOT)
    return [ROOT / p.decode() for p in output.split(b'\0') if p]


def slug(text: str) -> str:
    text = re.sub(r'<[^>]*>', '', text).lower()
    return ''.join('-' if c == ' ' else c for c in text
                   if c == ' ' or c in '-_' or unicodedata.category(c)[0] in 'LN')


def link_errors(source: Path) -> list[str]:
    errors = []
    content = re.sub(r'^\s*(```|~~~).*?^\s*\1\s*$', '', source.read_text(encoding='utf-8'), flags=re.MULTILINE | re.DOTALL)
    content = re.sub(r'`+[^`\n]*`+', '', content)
    for target in LINK.findall(content):
        parts = urlsplit(target.strip('<>'))
        if parts.scheme or parts.netloc or target.startswith('//'):
            continue
        destination = (source.parent / unquote(parts.path)).resolve() if parts.path else source
        if not destination.exists():
            errors.append(f'{source}: missing {target}')
            continue
        if parts.fragment and destination.is_file():
            headings = HEADING.findall(destination.read_text(encoding='utf-8'))
            counts: dict[str, int] = {}
            anchors = set()
            for heading in headings:
                base = slug(heading)
                count = counts.get(base, 0)
                counts[base] = count + 1
                anchors.add(base if count == 0 else f'{base}-{count}')
            if unquote(parts.fragment) not in anchors:
                errors.append(f'{source}: missing anchor {target}')
    return errors


def test_relative_markdown_links_resolve():
    paths = [p for p in tracked('*.md') if p.relative_to(ROOT).parts[0] not in {'openwiki', '.agents'}]
    errors = [error for path in paths for error in link_errors(path)]
    assert not errors, '\n'.join(errors)


def test_code_comment_doc_references_resolve():
    errors = []
    for path in tracked('*.py', '*.ts', '*.tsx', '*.sh'):
        if path.relative_to(ROOT).parts[0] in {'openwiki', '.agents'}:
            continue
        content = path.read_text(encoding='utf-8')
        if path.suffix == '.py':
            tokens = tokenize.generate_tokens(io.StringIO(content).readline)
            comments = '\n'.join(token.string for token in tokens if token.type == tokenize.COMMENT or (token.type == tokenize.STRING and token.string.lstrip('rRuUbBfF').startswith(('\"\"\"', "'''"))))
        else:
            comments = '\n'.join(line for line in content.splitlines() if re.match(r'\s*(//|/\*|\*|#)', line))
        for reference in DOC_PATH.findall(comments):
            if not (ROOT / reference).is_file():
                errors.append(f'{path.relative_to(ROOT)}: missing {reference}')
        for reference in ('AGENTS.md', 'DESIGN.md'):
            if reference in comments and not (ROOT / reference).is_file():
                errors.append(f'{path.relative_to(ROOT)}: missing {reference}')
        design = (ROOT / 'DESIGN.md').read_text(encoding='utf-8')
        for section in DESIGN_SECTION.findall(comments):
            if not re.search(rf'^#+\s+{re.escape(section)}(?:[.\s]|$)', design, re.MULTILINE):
                errors.append(f'{path.relative_to(ROOT)}: missing DESIGN.md §{section}')
    assert not errors, '\n'.join(errors)


def test_link_check_reports_a_missing_target(tmp_path):
    source = tmp_path / 'source.md'
    source.write_text('[missing](missing.md)', encoding='utf-8')
    assert len(link_errors(source)) == 1
