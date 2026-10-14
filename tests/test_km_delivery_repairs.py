"""Offline regression tests for reel salvage, Drive delivery and notifications."""
import array
import hashlib
import importlib
import json
import math
import os
import pathlib
import struct
import sys
import tempfile
import unittest
import wave
import zipfile
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest import mock

SRC = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / 'scripts'))


def write_wav(path, seconds=8, rate=8000):
    path = pathlib.Path(path)
    samples = array.array('h')
    for i in range(seconds * rate):
        samples.append(int(9000 * math.sin(2 * math.pi * 180 * i / rate)))
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(samples.tobytes())
    return samples, rate


def box(kind, body=b'12345678'):
    return struct.pack('>I4s', len(body) + 8, kind) + body


def fake_mp4():
    return box(b'ftyp') + box(b'moov') + box(b'mdat', b'voice-bytes')


class VoiceFallbackTests(unittest.TestCase):
    def test_partial_missing_is_classified_as_uncertain_not_missing(self):
        km_ctc = importlib.import_module('km_ctc')
        engine = object.__new__(km_ctc.Engine)
        engine.align = lambda lp, duration, texts: ([(0.0, 1.0, -1.0)] * len(texts), [])
        original = km_ctc.similarity

        def score(a, b):
            if a == 'AA' and b == 'AAXX': return .90
            if a == 'AA BB' and b == 'AAXX': return .71
            if a == 'BB' and b == 'AAXX': return .80
            if a == 'BB' and b: return .80
            return original(a, b)

        with mock.patch.object(km_ctc, 'similarity', side_effect=score):
            fit = engine.subset(None, 4.0, ['AA', 'BB'], 'AAXX')
        self.assertEqual(fit['partial_missing'], [1])
        self.assertEqual(fit['missing'], [])

    def test_analyze_partial_match_returns_soft_fit_without_missing_request(self):
        import numpy as np
        km_ctc = importlib.import_module('km_ctc')
        engine = object.__new__(km_ctc.Engine)
        engine.check_texts = lambda texts: list(texts)
        samples = np.full(8 * 8000, .15, dtype=np.float32)
        logits = np.zeros((800, 65), dtype=np.float32)
        engine.infer = lambda master, cache: (samples, 8000, logits, 'कथाको केही अंश')
        engine.subset = lambda *args: {'partial_missing': [1], 'selected': [0], 'missing': [],
                                       'ratio': .81, 'segments': [(0.1, 1.0, -1.0)], 'brackets': []}
        with tempfile.TemporaryDirectory() as tmp:
            master = pathlib.Path(tmp) / 'master.wav'
            write_wav(master)
            result = engine.analyze(master, ['नेपालको समाचार', 'आजको विवरण'], pathlib.Path(tmp) / 'ctc')
            self.assertTrue(result['best_effort'])
            self.assertEqual(result['missing_indices'], [])
            self.assertEqual(result['partial_missing_indices'], [1])
            self.assertIn('unverified', result['gates'].lower())

    def test_uncertain_halves_use_durable_one_line_audio_instead_of_estimated_cuts(self):
        import scripts.gemini_voice as voice
        km_ctc = importlib.import_module('km_ctc')
        class FakeEngine:
            def __init__(self, _model): pass
            def check_texts(self, _texts): return True
            def load(self): return True
            def analyze(self, audio, half_texts, _cache):
                source_hash = hashlib.sha256(pathlib.Path(audio).read_bytes()).hexdigest()
                if pathlib.Path(audio).parent.name == 'half1':
                    # Match the vhmkp failure shape: all indices were reported
                    # present even though the result contains a partial match.
                    return {'present_indices':[0,1],'missing_indices':[],
                            'partial_missing_indices':[1],'cuts_sec':[1.5],
                            'best_effort':True,'master_sha256':source_hash}
                return {'present_indices':[0,1],'missing_indices':[],
                        'partial_missing_indices':[],'cuts_sec':[4.0],
                        'best_effort':False,'master_sha256':source_hash}

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); work = root / 'one_call_voice' / 'fingerprint'
            texts = ['नेपालको समाचार सुरु भयो', 'आजको विवरण यहाँ छ', 'स्थानीय समाचार जारी', 'अर्को तथ्य प्रस्तुत']
            story = {'id': 'SYNTHETIC', 'cards': [{'vo': text, 'voice_tone': 'neutral'} for text in texts]}
            calls = []
            for half in (1, 2):
                folder = work / ('half%d' % half); folder.mkdir(parents=True)
                write_wav(folder / 'master.wav')
                (folder / 'response_metadata.json').write_text(json.dumps({'finish_reasons': ['STOP']}), encoding='utf-8')
            master = work / 'joined.wav'
            def fake_generate(_story, card_texts, target, *_args, **_kwargs):
                calls.extend(card_texts)
                target = pathlib.Path(target); target.parent.mkdir(parents=True, exist_ok=True)
                value = (texts.index(card_texts[0]) + 1) * 3000
                samples = array.array('h', [value] * 8000)
                with wave.open(str(target), 'wb') as out:
                    out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000); out.writeframes(samples.tobytes())
            with mock.patch.object(km_ctc, 'Engine', FakeEngine), mock.patch.object(voice, 'generate', side_effect=fake_generate):
                voice.build_two_halves(story, texts, master, work, root, recover_missing=True)
            self.assertEqual(calls, texts[:2])
            self.assertTrue(master.is_file())
            for half in (1, 2):
                folder = work / ('half%d' % half)
                check = json.loads((folder / 'cards' / 'split_checks.json').read_text(encoding='utf-8'))
                self.assertEqual(check['soft_fallback'], half==1)
                self.assertEqual(len(check['cards']), 2)
                self.assertTrue((folder / 'cards' / 'c01.wav').is_file())
                self.assertTrue((folder / 'cards' / 'c02.wav').is_file())
                if half == 1:
                    for local in (1, 2):
                        with wave.open(str(folder / 'cards' / ('c%02d.wav' % local)), 'rb') as clip:
                            values = array.array('h', clip.readframes(clip.getnframes()))
                        expected = local
                        self.assertEqual(max(values), expected * 3000)
            joined = json.loads((work / 'two_half_join.json').read_text(encoding='utf-8'))
            self.assertEqual([row['sync_method'] for row in joined['diagnostics']], ['isolated_per_card', 'ctc_boundaries'])
            self.assertTrue(voice.cached_voice_sync_status(work, len(texts))[0])
        print('CHECK PASS: uncertain combined audio is replaced by line-isolated clips with exact inter-card cuts')


class DriveUploadTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.puts = 0
        self.payloads = []

    def requester(self, method, url, headers, data, timeout, follow):
        self.calls.append((method, url, headers, data, timeout, follow))
        if method == 'POST' and url == 'https://token.invalid':
            return 302, {'Location': 'https://token.invalid/redeem'}, b''
        if method == 'GET' and url == 'https://token.invalid/redeem':
            return 200, {}, b'{"token":"TEST_TOKEN"}'
        if method == 'GET' and 'drive/v3/files?' in url:
            return 200, {}, b'{"files":[]}'
        if method == 'POST' and 'uploadType=resumable' in url:
            return 200, {'Location': 'https://upload.invalid/session'}, b''
        if method == 'PUT' and url == 'https://upload.invalid/session':
            self.puts += 1
            self.assert_streamed(data)
            if self.puts == 1:
                return 502, {}, b'test only'
            return 200, {}, b'{"id":"TEST_FILE_ID","name":"RV_TEST.mp4"}'
        raise AssertionError((method, url))

    def assert_streamed(self, data):
        self.assertTrue(hasattr(data, 'read'))
        self.payloads.append(data.read())

    def test_502_retries_and_success_is_durable_upload_result(self):
        from scripts.km_drive_upload import upload_all
        with tempfile.TemporaryDirectory() as tmp:
            mp4 = pathlib.Path(tmp) / 'RV_TEST.mp4'; mp4.write_bytes(fake_mp4())
            result = pathlib.Path(tmp) / 'km_drive'
            out = StringIO()
            with redirect_stdout(out):
                code = upload_all([mp4], {'DRIVE_TOKEN_URL':'https://token.invalid','DRIVE_TOKEN_SECRET':'TEST_ONLY','DRIVE_FOLDER_ID':'TEST_FOLDER'}, self.requester, lambda _seconds: None, result)
            self.assertEqual(code, 0)
            self.assertEqual(self.puts, 2)
            self.assertEqual(self.payloads, [fake_mp4(), fake_mp4()])
            self.assertEqual(result.read_text(encoding='utf-8'), 'ok RV_TEST.mp4\n')
            self.assertNotIn('TEST_ONLY', out.getvalue())
            self.assertNotIn('TEST_TOKEN', out.getvalue())

    def test_persistent_502_returns_failure_instead_of_green_status(self):
        from scripts.km_drive_upload import upload_all
        def always_502(method, url, headers, data, timeout, follow):
            if method == 'POST' and url == 'https://token.invalid':return 302, {'Location':'https://token.invalid/redeem'}, b''
            if method == 'GET' and url == 'https://token.invalid/redeem':return 200, {}, b'{"token":"TEST_TOKEN"}'
            if method == 'GET' and 'drive/v3/files?' in url:return 200, {}, b'{"files":[]}'
            if method == 'POST' and 'uploadType=resumable' in url:return 200, {'Location':'https://upload.invalid/session'}, b''
            if method == 'PUT':return 502, {}, b'not exposed'
            raise AssertionError((method, url))
        with tempfile.TemporaryDirectory() as tmp:
            mp4 = pathlib.Path(tmp) / 'RV_TEST.mp4'; mp4.write_bytes(fake_mp4())
            result = pathlib.Path(tmp) / 'km_drive'; out = StringIO()
            with redirect_stdout(out):
                code = upload_all([mp4], {'DRIVE_TOKEN_URL':'https://token.invalid','DRIVE_TOKEN_SECRET':'TEST_ONLY','DRIVE_FOLDER_ID':'TEST_FOLDER'}, always_502, lambda _seconds: None, result)
            self.assertEqual(code, 1)
            self.assertEqual(result.read_text(encoding='utf-8'), 'failed RV_TEST.mp4\n')
            self.assertNotIn('not exposed', out.getvalue())


class ArtifactAndBatchTests(unittest.TestCase):
    def test_manifest_artifact_is_restored_only_for_same_narration(self):
        artifacts = importlib.import_module('scripts.km_artifacts')
        story = {'id':'RV_TEST','cards':[{'vo':'नेपाल समाचार','voice_tone':'neutral'}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); out = root / 'out'; out.mkdir()
            stories = root / 'stories'; stories.mkdir()
            (stories/'RV_TEST.json').write_text(json.dumps(story, ensure_ascii=False), encoding='utf-8')
            video = fake_mp4(); digest = hashlib.sha256(video).hexdigest()
            manifest = {'story_id':'RV_TEST','narration_sha256':artifacts.narration_fingerprint(story),
                        'mp4_sha256':digest,'size_bytes':len(video)}
            zippath = root/'artifact.zip'
            with zipfile.ZipFile(zippath,'w') as zf:
                zf.writestr('RV_TEST.mp4',video)
                zf.writestr('RV_TEST.mp4.json',json.dumps(manifest))
            item={'id':123,'name':'km-reels-55','archive_download_url':'https://api.invalid/artifact/123',
                  'workflow_run':{'id':55}}
            with mock.patch.object(artifacts,'ROOT',root), mock.patch.object(artifacts,'OUT',out), \
                 mock.patch.object(artifacts,'_artifact_rows',return_value=[item]), \
                 mock.patch.object(artifacts,'_download_archive',return_value=zippath):
                restored=artifacts.restore_pending({'RV_TEST':story},token='TEST_TOKEN',repo='owner/repo',current_run='99')
            self.assertEqual(restored,{'RV_TEST'})
            self.assertEqual((out/'RV_TEST.mp4').read_bytes(),video)
            marker=json.loads((out/'.km_artifact_restored'/'RV_TEST.json').read_text(encoding='utf-8'))
            self.assertTrue(marker['manifest_verified'])

    def test_artifact_lookup_bounds_old_archive_downloads(self):
        artifacts = importlib.import_module('scripts.km_artifacts')
        story = {'id':'RV_TEST','cards':[{'vo':'नेपाल समाचार','voice_tone':'neutral'}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); out = root / 'out'; out.mkdir()
            zippath = root / 'empty.zip'
            with zipfile.ZipFile(zippath, 'w'):
                pass
            rows=[{'id':i,'name':'km-reels-%s'%i,'archive_download_url':'https://api.invalid/%s'%i,
                   'workflow_run':{'id':i}} for i in range(20)]
            with mock.patch.object(artifacts, 'OUT', out), \
                 mock.patch.object(artifacts, '_artifact_rows', return_value=rows), \
                 mock.patch.object(artifacts, '_download_archive', return_value=zippath) as download:
                artifacts.restore_pending({'RV_TEST':story}, token='TEST_TOKEN', repo='owner/repo', current_run='99')
            self.assertEqual(download.call_count, artifacts.MAX_ARTIFACT_DOWNLOADS)

    def test_existing_valid_mp4_skips_voice_and_render(self):
        make_reel=importlib.import_module('make_reel')
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/'out').mkdir()
            (root/'out'/'RV_READY.mp4').write_bytes(fake_mp4())
            old=make_reel.ROOT;make_reel.ROOT=root
            try:
                with mock.patch.object(make_reel,'run',side_effect=AssertionError('must reuse existing render')):
                    self.assertEqual(make_reel.voice_and_render('RV_READY'),0)
            finally:make_reel.ROOT=old

    def test_batch_continues_after_one_story_fails(self):
        make_reel=importlib.import_module('make_reel')
        artifacts=importlib.import_module('scripts.km_artifacts')
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/'out').mkdir();(root/'stories').mkdir()
            story={'cards':[{'vo':'test','voice_tone':'neutral'}]}
            for sid in ('RV_FAIL','RV_NEXT'):(root/'stories'/(sid+'.json')).write_text(json.dumps(story))
            old=make_reel.ROOT;make_reel.ROOT=root;calls=[]
            def render(sid,recover=False):
                calls.append(sid)
                return 2 if sid=='RV_FAIL' else 0
            try:
                with mock.patch.object(make_reel,'ensure_layout',return_value=True), \
                     mock.patch.object(make_reel,'valid_story',return_value=story), \
                     mock.patch.object(make_reel,'voice_and_render',side_effect=render), \
                     mock.patch.object(artifacts,'restore_pending',return_value=set()), \
                     mock.patch.object(artifacts,'valid_mp4',return_value=False):
                    code=make_reel.process_stories(['RV_FAIL','RV_NEXT'],recover=True)
            finally:make_reel.ROOT=old
            self.assertEqual(code,1)
            self.assertEqual(calls,['RV_FAIL','RV_NEXT'])

    def test_published_event_is_distinct_and_success_copy_waits_for_state(self):
        stub_state=SimpleNamespace(ROOT=pathlib.Path('.'),StateError=RuntimeError,published_candidates=lambda:[])
        with mock.patch.dict(sys.modules,{'km_state':stub_state}):
            notify=importlib.import_module('scripts.km_notify')
        old_meta=os.environ.get('META_ENABLE')
        os.environ['META_ENABLE']='true'
        try:
            with mock.patch.object(notify,'summaries',return_value=[('RV_DONE','early note')]), \
                 mock.patch.object(notify,'_drive_failures',return_value=set()), \
                 mock.patch.object(notify,'_run_published_candidates',return_value=set()), \
                 mock.patch.object(notify.km_state,'published_candidates',return_value=['RV_DONE']):
                events=list(notify.events())
            self.assertEqual(events[0][1],'published')
            self.assertIn('accepted on all 6 enabled platforms',events[0][2])
        finally:
            if old_meta is None:os.environ.pop('META_ENABLE',None)
            else:os.environ['META_ENABLE']=old_meta

    def test_current_run_success_notice_requires_every_enabled_platform(self):
        stub_state=SimpleNamespace(ROOT=pathlib.Path('.'),StateError=RuntimeError,published_candidates=lambda:[])
        with mock.patch.dict(sys.modules,{'km_state':stub_state}):
            notify=importlib.import_module('scripts.km_notify')
        old_meta=os.environ.get('META_ENABLE')
        os.environ['META_ENABLE']='true'
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result=pathlib.Path(tmp)/'km_publish_result.txt'
                result.write_text(''.join('accepted RV_NOW %s post-id\n'%p for p in
                    ('tiktok','youtube','linkedin','facebook','instagram','threads')),encoding='utf-8')
                with mock.patch.object(notify,'RESULT',result):
                    self.assertEqual(notify._run_published_candidates(),{'RV_NOW'})
                    result.write_text(result.read_text(encoding='utf-8').replace('accepted RV_NOW threads','failed RV_NOW threads'))
                    self.assertEqual(notify._run_published_candidates(),set())
        finally:
            if old_meta is None:os.environ.pop('META_ENABLE',None)
            else:os.environ['META_ENABLE']=old_meta

    def test_legacy_deferred_notice_backfill_requires_every_platform_receipt(self):
        fcntl_stub=SimpleNamespace(LOCK_EX=1,flock=lambda *_args:None)
        with mock.patch.dict(sys.modules,{'fcntl':fcntl_stub}):
            spec=importlib.util.spec_from_file_location('km_state_published_test',SRC/'scripts'/'km_state.py')
            state=importlib.util.module_from_spec(spec);spec.loader.exec_module(state)
        sid='RV_LEGACY';files={
            'out/done/'+sid+'.json':json.dumps({'story_id':sid,'publisher_version':'5.7'}).encode(),
            'out/notifications/'+sid+'.json':json.dumps({'state':'sent','body':'Posting deferred or reel incomplete.'}).encode(),
        }
        for platform in ('tiktok','youtube','linkedin','facebook','instagram','threads'):
            files['out/buffer_receipts/'+sid+'_'+platform+'.json']=json.dumps({'state':'accepted'}).encode()
        class GitResult:
            stdout=('out/done/'+sid+'.json\n').encode()
        with mock.patch.dict(os.environ,{'META_ENABLE':'true'}), \
             mock.patch.object(state,'latest',return_value='HEAD'), \
             mock.patch.object(state,'git',return_value=GitResult()), \
             mock.patch.object(state,'read_at',side_effect=lambda _head,path:files.get(path)):
            self.assertEqual(state.published_candidates(),[sid])
            files['out/buffer_receipts/'+sid+'_threads.json']=json.dumps({'state':'pending'}).encode()
            self.assertEqual(state.published_candidates(),[])

    def test_notification_events_have_independent_claims_and_rejected_send_can_retry(self):
        fcntl_stub=SimpleNamespace(LOCK_EX=1,flock=lambda *_args:None)
        with mock.patch.dict(sys.modules,{'fcntl':fcntl_stub}):
            spec=importlib.util.spec_from_file_location('km_state_notification_test',SRC/'scripts'/'km_state.py')
            state=importlib.util.module_from_spec(spec);spec.loader.exec_module(state)
        sid='RV_NOTIFY';files={'out/notifications/'+sid+'.json':json.dumps({'state':'sent','body':'early summary'}).encode()}
        def transaction(builder,_message):
            files.update(builder('HEAD'))
        state.read_at=lambda _head,path:files.get(path)
        state.transaction=transaction
        path,owner=state.notification_claim(sid,'published success',event='published')
        self.assertTrue(path.endswith(sid+'_published.json'))
        state.notification_result(path,owner,'failed')
        retry_path,_=state.notification_claim(sid,'published success retry',event='published')
        self.assertEqual(retry_path,path)
        with self.assertRaises(state.StateError):
            state.notification_claim(sid,'duplicate success',event='published')

    def test_workflow_wires_read_only_artifact_restore_and_visible_fact_notes(self):
        workflow=(SRC/'.github'/'workflows'/'km_reel.yml').read_text(encoding='utf-8')
        self.assertIn('actions: read',workflow)
        self.assertIn('km-reels-${{ github.run_id }}',workflow)
        self.assertIn('python scripts/km_drive_upload.py',workflow)
        self.assertIn("grep -qEi 'FACT CHECK:|NOTE \\(built because you approved it\\):' /tmp/km_run.log",workflow)
        self.assertIn("grep -q '^failed ' /tmp/km_drive",workflow)


if __name__ == '__main__':
    unittest.main(verbosity=2)
