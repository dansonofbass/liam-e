import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FORMS = ROOT / '.github' / 'ISSUE_TEMPLATE'
EXPECTED = {
    '01-bug.yml': [('observed', True), ('expected', True), ('steps', True), ('version', True), ('area', True), ('acceptance', True)],
    '02-change.yml': [('problem', True), ('proposal', True), ('out-of-scope', False), ('contracts', False), ('acceptance', True), ('verification', True)],
    '03-evaluation.yml': [('question', True), ('current', True), ('candidates', True), ('access', True), ('criteria', True), ('breakdown', False)],
    '04-subtask.yml': [('parent', True), ('prerequisites', True), ('goal', True), ('work', True), ('out-of-scope', True), ('acceptance', True), ('verification', True), ('stop', False)],
}


def test_issue_forms_keep_field_ids_and_required_flags():
    for name, expected in EXPECTED.items():
        form = yaml.safe_load((FORMS / name).read_text())
        assert [(f.get('id'), f.get('validations', {}).get('required', False)) for f in form['body'] if f['type'] != 'markdown'] == expected
        assert form['labels'] == (['bug'] if name == '01-bug.yml' else ['enhancement'])


def test_config_keeps_blank_issues_off_and_private_reporting():
    config = yaml.safe_load((FORMS / 'config.yml').read_text())
    assert config['blank_issues_enabled'] is False
    assert config['contact_links'][0]['url'] == 'https://github.com/plagor44-ux/liam-e/security/advisories/new'


def test_templates_contain_no_german():
    pattern = re.compile(r'\b(und|nicht|oder|bitte|wird|für|über|ist|Beschreibung|Ergebnis|Fehler)\b', re.IGNORECASE)
    for path in [*FORMS.glob('*.yml'), ROOT / '.github' / 'pull_request_template.md']:
        assert not pattern.search(path.read_text()), str(path)
