"""Real Global installers and Magi scan; only browser/HTTP are fixtures."""
import contextlib
import io
import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TITLE = '【PSA10】 ミュウツー (AR) {183/165} [SV2a/ポケモンカード151] 1枚の通販'


class Page:
    def __init__(self, changed=False):
        self.item = ''
        self.titles = {'1': TITLE, '2': TITLE if changed else TITLE.replace('ミュウツー', 'ペルシアン'),
                       '3': TITLE + ' SOLD OUT', '4': TITLE.replace('1枚', '2枚セット'), '5': TITLE}

    def goto(self, url, **kwargs):
        self.item = url.rsplit('/', 1)[-1]
        if self.item == '5':
            raise TimeoutError('browser unavailable')

    def wait_for_timeout(self, *_args):
        pass

    def evaluate(self, script):
        if 'slice(0,1800)' in script:
            return [{'href': 'https://magi.camp/items/' + k, 'anchor': t, 'text': t + ' 25000円'}
                    for k, t in self.titles.items()]
        return False

    def title(self):
        return self.titles[self.item]

    def locator(self, *_args):
        return self

    def inner_text(self, **_kwargs):
        return self.title()


def fixture(changed=False):
    import requests
    calls = []

    def request(session, method, url, **kwargs):
        calls.append([method, url, kwargs.get('params')])
        assert method.upper() == 'GET'
        code, payload = 404, {}
        if '/ja/sets/SV2a/' in url or '/en/cards/SV2a-183' in url:
            code = 200
            payload = {'id': 'SV2a-183', 'localId': '183',
                       'name': 'Mewtwo' if '/en/' in url else 'ミュウツー',
                       'set': {'id': 'SV2a', 'name': 'Pokemon Card 151' if '/en/' in url else 'ポケモンカード151',
                               'cardCount': {'official': 165}}, 'variants': {'normal': True}}
        response = requests.Response()
        response.status_code = code
        response._content = json.dumps(payload).encode()
        response.url = url
        return response

    with patch.object(requests.sessions.Session, 'request', request), contextlib.redirect_stdout(io.StringIO()):
        import v4_global_marketplace_notify_resilient as runner
        with patch.object(sys, 'argv', ['runner', '--help']):
            try:
                runner.main()
            except SystemExit as status:
                assert status.code == 0
        runner.confirmed.install_global_external_market_stack()
        import v4_global_marketplace_magi_native_identity as native
        import v4_global_marketplace_magi_recovery_budget as budget
        rows, status = native.scan_magi_native_inventory(Page(changed), (), observed_at=datetime(2026,9,10,tzinfo=timezone.utc))
        reserve = budget.CachedRecoveryResolver()
        caps = [budget._MAX_RECOVERY_REQUESTS, budget._CARD_IDENTITY_RESERVE_REQUESTS,
                reserve._nonpriority_request_cap]
        reserve.close()
        return {'manifest': getattr(status, 'manifest', None), 'exact': len(rows), 'calls': calls,
                'budgets': caps}


class MagiManifestTests(unittest.TestCase):
    def run_fixture(self, changed=False):
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'changed' if changed else 'same'],
                               cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        return json.loads(child.stdout)

    def test_deterministic_manifest_and_no_diagnostic_network(self):
        first, second = self.run_fixture(), self.run_fixture()
        self.assertIsNotNone(first['manifest'])
        self.assertEqual(first['manifest'], second['manifest'])
        self.assertEqual(first['calls'], second['calls'])
        self.assertEqual(first['budgets'], [50, 15, 35])
        # Baseline real-runtime HTTP trace: one coordinate and one Latin alias.
        self.assertEqual(len(first['calls']), 2)
        self.assertEqual(first['exact'], 1)

    def test_success_rejections_and_detail_error_are_all_traceable(self):
        result = self.run_fixture()
        self.assertIsNotNone(result['manifest'])
        rows = result['manifest']['rows']
        self.assertEqual(len(rows), 5)
        self.assertEqual([r['status'] for r in rows], ['EXACT','NO_MATCH','NO_MATCH','NO_MATCH','ERROR'])
        self.assertEqual(rows[0]['coordinate']['card_id'], 'SV2a-183')
        self.assertEqual(rows[4]['reason'], 'detail_error')
        self.assertTrue(all('budget_delta' in r and 'url' in r for r in rows))

    def test_single_url_status_change_is_identifiable(self):
        a, b = self.run_fixture(), self.run_fixture(True)
        self.assertIsNotNone(a['manifest'])
        before = {r['url']: r['status'] for r in a['manifest']['rows']}
        after = {r['url']: r['status'] for r in b['manifest']['rows']}
        self.assertEqual([u for u in before if before[u] != after[u]], ['https://magi.camp/items/2'])

    def test_manifest_is_bounded_and_strips_non_public_url_data(self):
        from types import SimpleNamespace
        from v4_global_marketplace_magi_rejection_probe import MagiManifest
        manifest = MagiManifest(203)
        for i in range(203):
            manifest.record(SimpleNamespace(url=f'https://magi.camp/items/{i}?private=test#fragment'),
                            'NOT_EVALUATED', 'detail_cap', {}, {})
        payload = manifest.payload()
        self.assertEqual(len(payload['rows']), 200)
        self.assertEqual(payload['truncated'], 3)
        self.assertEqual(payload['rows'][0]['url'], 'https://magi.camp/items/0')
        self.assertNotIn('private', json.dumps(payload))


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    print(json.dumps(fixture(sys.argv[-1] == 'changed')))
