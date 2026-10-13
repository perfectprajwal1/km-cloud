#!/usr/bin/env python3
"""Offline tests for the variety layer (scripts/km_selection.py + converter hook + history state).
No network, no keys, no voice. Strip drawing is stubbed except where a test says otherwise.
Run: python tests/test_selection.py"""
import collections, contextlib, copy, importlib.util, io, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
SRC = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC / 'scripts'))
import script_to_story as S, km_selection as K

def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)

def real_stories():
    out = []
    for d in sorted((SRC / 'inbox').glob('*')):
        txt = next(iter(sorted(d.glob('*.txt'))), None)
        if not txt: continue
        try: rid, res, pr = quiet(S.build, txt.read_text(encoding='utf-8'), False, {})
        except BaseException: continue
        out.append(res[0])
    return out

def stub_render(story, safe, sdir):
    for i, c in enumerate(story['cards']):
        g = c['strip'].pop('_gen', None)
        if g: c['strip']['anim'] = {'kind': g['kind']}; c['strip']['src'] = 'x.png'

def run_layout(story, root, fail_strip_kinds=()):
    """layout_with_fallback with drawing stubbed; K.ROOT-style root is a temp dir."""
    calls = []
    def fake(story_, safe, sdir):
        calls.append(1)
        for c in story_['cards'] if len(calls) == 1 else []:
            g = c['strip'].get('_gen')
            if g and g['kind'] in fail_strip_kinds: raise RuntimeError('asset missing ' + g['kind'])
        stub_render(story_, safe, sdir)
    old = (S.render_strips, S.ROOT)
    S.render_strips = fake; S.ROOT = pathlib.Path(root)
    (pathlib.Path(root) / 'scripts').mkdir(exist_ok=True)
    try: return quiet(S.layout_with_fallback, copy.deepcopy(story), 'T', root)
    finally: S.render_strips, S.ROOT = old

def ident(st): return [(c['vo'], c.get('voice_tone', 'neutral'), c['type'] == 'engage') for c in st['cards']]

class KnownFailures(unittest.TestCase):
    def cand(self, vo, idx=2):
        m, s, f = K.candidates(vo, '', idx, S)
        return {x['kind'] for x in m if not x['payload'].get('plain_fallback')}, {x['kind'] for x in s}
    def test_conditional_sentence_is_not_a_quote(self):
        for vo in ('यदि पानी परे बाढी आउँछ भने सतर्क रहनुपर्छ।', 'मन्त्रीले यदि सडक बनेन भने आन्दोलन हुन्छ भने।'):
            m, s = self.cand(vo); self.assertNotIn('quote', m, vo); self.assertNotIn('quote', s, vo); self.assertNotIn('voiceprint', s, vo)
    def test_cha_is_not_six(self):
        for vo in ('स्थिति सामान्य छ।', 'सडक खुला छ, यातायात चलिरहेको छ।'):
            m, s = self.cand(vo); self.assertFalse(m & {'bignum', 'scale', 'date', 'change'}, vo); self.assertFalse(s & {'stat', 'units', 'waffle', 'track'}, vo)
    def test_cancelled_or_uncertain_events_not_shown_as_real(self):
        for vo in ('१२ बजे हुने खेल रद्द भयो, कार्यक्रम हुँदैन।', 'आज १२ बजे बैठक बस्ने सम्भावना छ।', 'अफवाह छ कि ५ जना घाइते भए।'):
            m, s = self.cand(vo); self.assertNotIn('next', m, vo); self.assertNotIn('bignum', m, vo); self.assertFalse(s & {'schedule', 'stat', 'units', 'incident'}, vo)
    def test_plain_fallback_cannot_displace_default_card(self):
        # A line the converter gave a Scale card must not be turned into plain Points.
        for st in real_stories():
            base = [c['type'] for c in st['cards']]
            done = quiet(K.select_story, copy.deepcopy(st), None, S, tempfile.mkdtemp())
            for b, c in zip(base, done['cards']):
                if b in ('scale', 'bignum'): self.assertNotEqual(K.mainkey_of(c), 'main:points_plain')

class Eligibility(unittest.TestCase):
    def test_real_stories_only_use_eligible_designs_and_keep_narration(self):
        stories = real_stories(); self.assertGreaterEqual(len(stories), 5)
        for st in stories:
            before = ident(st)
            done = quiet(K.select_story, copy.deepcopy(st), None, S, tempfile.mkdtemp())
            self.assertEqual(ident(done), before)
            for ln, c in zip(done['selection']['lines'], [c for c in done['cards'] if c['type'] != 'engage']):
                self.assertIn(K.mainkey_of(c), ln['eligible']); self.assertIn('strip:' + c['strip']['_gen']['kind'], ln['eligible'])
    def test_no_adjacent_repeat_when_alternative_exists(self):
        mains = [{'kind': k, 'payload': {'type': k}, 'score': 80, 'reason': '', 'evidence': []} for k in ('bignum', 'scale')]
        strips = [{'kind': k, 'payload': {'kind': k}, 'score': 80, 'reason': '', 'evidence': []} for k in ('stat', 'phrase')]
        m, s, _, _ = K.choose(mains, strips, {'reels': []}, {'main': 'bignum', 'strip': 'stat'})
        self.assertEqual((m['kind'], s['kind']), ('scale', 'phrase'))
        only = [mains[0]]
        m, s, _, _ = K.choose(only, strips, {'reels': []}, {'main': 'bignum', 'strip': 'stat'})
        self.assertEqual(m['kind'], 'bignum')  # no alternative: still builds

class Coverage(unittest.TestCase):
    def test_rotation_reaches_every_design_and_ties_do_not_starve(self):
        mains = [{'kind': k, 'payload': {'type': k}, 'score': 90, 'reason': '', 'evidence': []} for k in K.MAINS if k != 'engage']
        strips = [{'kind': k, 'payload': {'kind': k}, 'score': 90, 'reason': '', 'evidence': []} for k in K.STRIPS]
        hist = {'reels': []}; seen = collections.Counter()
        for r in range(40):
            prev = {}; sel = []
            for line in range(5):
                m, s, _, _ = K.choose(mains, strips, hist, prev); prev = {'main': m['kind'], 'strip': s['kind']}
                sel += ['main:' + m['kind'], 'strip:' + s['kind']]
            hist['reels'].append({'id': str(r), 'selected': sel}); seen.update(sel)
        for k in K.MAINS:
            if k != 'engage': self.assertGreater(seen['main:' + k], 0, k)
        for k in K.STRIPS: self.assertGreater(seen['strip:' + k], 0, k)
        self.assertLess(max(v for k, v in seen.items() if k.startswith('strip:')) / max(1, min(v for k, v in seen.items() if k.startswith('strip:'))), 4)

class SoftFailures(unittest.TestCase):
    def setUp(self):
        self.story = real_stories()[0]; self.root = tempfile.mkdtemp()
    def check_default(self, got):
        self.assertNotIn('selection', got); self.assertEqual(ident(got), ident(self.story))
        self.assertTrue(all(c['strip'].get('anim') or c['strip']['kind'] in ('none', 'echo') for c in got['cards']))
    def test_works_normally(self):
        got = run_layout(self.story, self.root); self.assertIn('selection', got); self.assertEqual(ident(got), ident(self.story))
        self.assertEqual(got['selection']['render_seal'], K.digest(got['cards']))
    def test_missing_history_ok(self): self.assertIn('selection', run_layout(self.story, self.root))
    def test_malformed_history_falls_back(self):
        p = pathlib.Path(self.root) / 'out/selection'; p.mkdir(parents=True); (p / 'history.json').write_text('{not json')
        self.check_default(run_layout(self.story, self.root))
    def test_unwritable_history_dir_falls_back(self):
        (pathlib.Path(self.root) / 'out').write_text('a file, not a folder')
        self.check_default(run_layout(self.story, self.root))
    def test_selector_exception_falls_back(self):
        old = K.select_story; K.select_story = lambda *a, **k: 1 / 0
        try: self.check_default(run_layout(self.story, self.root))
        finally: K.select_story = old
    def test_selector_that_changes_narration_is_rejected(self):
        old = K.select_story
        def bad(st, *a):
            st['cards'][1]['vo'] += ' x'; return st
        K.select_story = bad
        try: self.check_default(run_layout(self.story, self.root))
        finally: K.select_story = old
    def test_unavailable_strip_asset_falls_back(self):
        kinds = {c['strip']['_gen']['kind'] for c in run_layout.__globals__['K'].select_story(copy.deepcopy(self.story), None, S, tempfile.mkdtemp())['cards'] if c['strip'].get('_gen')}
        self.check_default(run_layout(self.story, tempfile.mkdtemp(), fail_strip_kinds=kinds))
    def test_env_switch_off(self):
        os.environ['KM_SELECTION'] = '0'
        try: self.check_default(run_layout(self.story, self.root))
        finally: del os.environ['KM_SELECTION']
    def test_all_real_stories_build(self):
        for st in real_stories():
            got = run_layout(st, tempfile.mkdtemp()); self.assertEqual(ident(got), ident(st)); self.assertTrue(got['cards'])

class Commit(unittest.TestCase):
    def mp4(self, d, ok=True):
        p = pathlib.Path(d) / 'x.mp4'
        if ok: subprocess.run(['ffmpeg', '-y', '-v', 'quiet', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:d=1', '-c:v', 'mpeg4', str(p)], check=True)
        else: p.write_bytes(b'')
        return p
    def setUp(self):
        self.root = tempfile.mkdtemp(); (pathlib.Path(self.root) / 'scripts').mkdir()
        self.story = run_layout(real_stories()[0], self.root); self.sp = pathlib.Path(self.root) / 's.json'
        self.sp.write_text(json.dumps(self.story))
    def test_history_only_after_good_render_and_never_double_counts(self):
        with self.assertRaises(Exception): K.commit(self.sp, self.mp4(self.root, ok=False), self.root)
        self.assertFalse((pathlib.Path(self.root) / 'out/selection/history.json').exists())
        self.assertTrue(K.commit(self.sp, self.mp4(self.root), self.root))
        h = json.loads((pathlib.Path(self.root) / 'out/selection/history.json').read_text())
        self.assertEqual(len(h['reels']), 1); total = sum(h['used_total'].values())
        self.assertFalse(K.commit(self.sp, self.mp4(self.root), self.root))
        h2 = json.loads((pathlib.Path(self.root) / 'out/selection/history.json').read_text()); self.assertEqual(sum(h2['used_total'].values()), total)
    def test_cli_commit_never_fails_the_reel(self):
        r = subprocess.run([sys.executable, str(SRC / 'scripts/km_selection.py'), 'commit', str(self.sp), '/no/such.mp4'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0); self.assertIn('NOTE', r.stdout)
    def test_legacy_story_without_selection_is_ignored(self):
        legacy = dict(self.story); legacy.pop('selection'); self.sp.write_text(json.dumps(legacy))
        self.assertFalse(K.commit(self.sp, self.mp4(self.root), self.root))

def git(*a, cwd=None):
    p = subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)
    if p.returncode: raise RuntimeError(p.stderr)
    return p.stdout.strip()

class StateRoundTrip(unittest.TestCase):
    def test_two_clean_runners_share_history_and_failure_is_soft(self):
        base = pathlib.Path(tempfile.mkdtemp()); remote = base / 'r.git'; git('init', '--bare', '--initial-branch=main', str(remote))
        seed = base / 'seed'; git('clone', str(remote), str(seed))
        for k, v in (('user.email', 't@e.invalid'), ('user.name', 't')): git('config', k, v, cwd=seed)
        (seed / 'scripts').mkdir(); shutil.copy2(SRC / 'scripts/km_state.py', seed / 'scripts'); (seed / 'x').write_text('1')
        git('add', '.', cwd=seed); git('commit', '-m', 's', cwd=seed); git('push', 'origin', 'main', cwd=seed)
        def runner(n):
            d = base / n; git('clone', str(remote), str(d))
            for k, v in (('user.email', 't@e.invalid'), ('user.name', 't')): git('config', k, v, cwd=d)
            return d
        def render(d, rid, kinds):
            root = str(d); st = copy.deepcopy(real_stories()[0]); st['id'] = rid
            (d / 'scripts/km_selection.py').write_text((SRC / 'scripts/km_selection.py').read_text(encoding='utf-8'), encoding='utf-8')
            got = run_layout(st, root); sp = d / 's.json'; sp.write_text(json.dumps(got))
            mp = Commit.mp4(None, d); K.commit(sp, mp, root)
        a, b = runner('a'), runner('b')
        render(a, 'REEL_A', None); render(b, 'REEL_B', None)
        run = lambda d: subprocess.run([sys.executable, 'scripts/km_state.py', 'selection-history'], cwd=d, capture_output=True, text=True)
        self.assertEqual(run(a).returncode, 0); self.assertEqual(run(b).returncode, 0)
        c = runner('c'); h = json.loads((c / 'out/selection/history.json').read_text())
        self.assertEqual({r['id'] for r in h['reels']}, {'REEL_A', 'REEL_B'})
        self.assertEqual(run(c).returncode, 0)  # nothing new: no change, no error
        # clean runner restoring it carries usage forward
        self.assertEqual(sum(h['used_total'].values()), sum(len(r['selected']) for r in h['reels']))
        (c / 'out/selection/history.json').write_text('garbage'); self.assertNotEqual(run(c).returncode, 0)  # reported, caller treats as soft
        # progress() wraps it softly: source check
        self.assertIn('except Exception as e: print(\'NOTE: variety history not saved', (SRC / 'scripts/km_state.py').read_text(encoding='utf-8'))

if __name__ == '__main__':
    r = unittest.main(exit=False, verbosity=1)
    print('CHECK PASS: selection tests' if r.result.wasSuccessful() else 'CHECK FAIL: selection tests')
    sys.exit(0 if r.result.wasSuccessful() else 1)
