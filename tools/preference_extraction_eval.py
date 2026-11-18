"""Synthetic-only preference evaluation. Offline by default; --live explicitly calls Mistral."""
import argparse
import asyncio
import json
from pathlib import Path

from api.preferences.extraction import extract, validate_output
from env.mail import env

FIXTURES = Path(__file__).resolve().parents[1] / 'apps/api/tests/fixtures/preference_extraction.json'


async def main(live=False):
    """Print per case what would be stored; `rejected` means validation dropped the model output.

    A rejected output stores nothing, so it matches an expected 0. Other errors never match.
    """
    matched = model_matched = 0
    cases = json.loads(FIXTURES.read_text())
    for case in cases:
        try:
            items = (await extract(case['text'], env.mail_chat_model) if live else
                     validate_output(json.dumps({'candidates': case['candidates']}), case['text']))
            got = len(items)
        except ValueError:
            got = 'rejected'
        except Exception:
            got = 'error'
        stored = 0 if got == 'rejected' else got
        matched += stored == case['expected']
        model_matched += got == case['expected']
        print(f"{case['id']} expected={case['expected']} got={got}")
    print(f'stored {matched}/{len(cases)}, model without validation {model_matched}/{len(cases)}')
    return 0 if matched == len(cases) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    raise SystemExit(asyncio.run(main(parser.parse_args().live)))
