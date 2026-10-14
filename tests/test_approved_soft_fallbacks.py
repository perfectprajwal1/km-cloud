"""Offline checks that uncertain voice/alignment results do not block approval."""
import array
import contextlib
import importlib
import io
import json
import math
import os
import pathlib
import runpy
import struct
import sys
import tempfile
import types
import unittest
import wave
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import gemini_voice as voice
import km_ctc


def write_wav(path, samples, rate=8000):
    path = pathlib.Path(path)
    raw = array.array('h', samples)
    if sys.byteorder != 'little': raw.byteswap()
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(raw.tobytes())
    return array.array('h', raw)


def read_wav(path):
    with wave.open(str(path), 'rb') as src:
        raw = array.array('h', src.readframes(src.getnframes()))
    if sys.byteorder != 'little': raw.byteswap()
    return raw


class SoftSplitTests(unittest.TestCase):
    def split_case(self, samples, cuts, texts=None):
        texts = texts or ['पहिलो समाचार विवरण।', 'दोस्रो समाचार विवरण।']
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root = pathlib.Path(tmp); master = root / 'master.wav'
            source = write_wav(master, samples)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                report = voice.split_audio(master, texts, root / 'cards', cuts=cuts)
            cards = [read_wav(root / 'cards' / ('c%02d.wav' % (i + 1))) for i in range(len(texts))]
            self.assertTrue(report['soft_fallback'])
            self.assertEqual(sum(map(len, cards)), len(source))
            self.assertEqual(array.array('h', (sample for card in cards for sample in card)), source)
            self.assertIn('NOTE:', out.getvalue())
            return report

    def test_cut_through_speech_falls_back_without_losing_samples(self):
        samples = [int(9000 * math.sin(2 * math.pi * 180 * i / 8000)) for i in range(16000)]
        self.split_case(samples, [1.0])
        print('CHECK PASS: boundary confidence failure becomes a note; all source samples are retained')

    def test_too_short_card_and_invalid_generated_cuts_fall_back(self):
        samples = [int(7000 * math.sin(2 * math.pi * 150 * i / 8000)) for i in range(16000)]
        self.split_case(samples, [.1])
        self.split_case(samples, [100.0])
        print('CHECK PASS: short-card and out-of-range generated-cut doubts use a soft split')

    def test_no_detectable_speech_is_a_note_and_silent_samples_are_preserved(self):
        self.split_case([0] * 16000, [1.0])
        print('CHECK PASS: no-speech heuristic does not block the approved audio split')

    def test_ctc_soft_split_needs_no_numpy_and_has_ordered_cuts(self):
        samples = [int(7000 * math.sin(2 * math.pi * 150 * i / 8000)) for i in range(24000)]
        with mock.patch.dict(sys.modules, {'numpy': None}):
            cuts = km_ctc.soft_cut_points(samples, 8000, ['एक', 'दुई', 'तीन'])
        self.assertEqual(len(cuts), 2)
        self.assertLess(0, cuts[0]); self.assertLess(cuts[0], cuts[1]); self.assertLess(cuts[1], 3)
        print('CHECK PASS: CTC fallback cuts are generated with the standard library and remain ordered')

    def test_production_entry_enables_soft_mode_but_offline_fixture_stays_strict(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root = pathlib.Path(tmp); (root / 'scripts').mkdir(); (root / 'stories').mkdir()
            (root / 'scripts' / 'gemini_voice.py').write_text('# test path anchor', encoding='utf-8')
            story = {'id':'RV_TEST','cards':[{'vo':'नमुना समाचार।','voice_tone':'neutral'}]}
            (root / 'stories' / 'RV_TEST.json').write_text(json.dumps(story, ensure_ascii=False), encoding='utf-8')
            fixture = root / 'fixture.wav'; write_wav(fixture, [1000] * 8000)
            cuts_file = root / 'cuts.json'; cuts_file.write_text('[]', encoding='utf-8')
            old_file = voice.__file__; calls = []
            def fake_build(_story, _texts, master, *_args, **_kwargs):
                write_wav(master, [1000] * 8000)
                return []
            def fake_split(_master, _texts, _dest, *_args, **kwargs):
                calls.append(kwargs.get('auto_soft'))
                return {'cards':[{'card':1,'duration_sec':1.0}], 'soft_fallback':True}
            try:
                voice.__file__ = str(root / 'scripts' / 'gemini_voice.py')
                old_cwd = pathlib.Path.cwd()
                os.chdir(root)
                old_argv = sys.argv[:]
                try:
                    sys.argv = ['gemini_voice.py', 'stories/RV_TEST.json']
                    with mock.patch.object(voice, 'build_two_halves', side_effect=fake_build), \
                         mock.patch.object(voice, 'split_audio', side_effect=fake_split):
                        with self.assertRaises(SystemExit): voice.main()
                    self.assertEqual(calls, [True])
                    calls.clear()
                    sys.argv = ['gemini_voice.py', 'stories/RV_TEST.json', '--audio', str(fixture), '--cuts', str(cuts_file)]
                    with mock.patch.object(voice, 'split_audio', side_effect=fake_split):
                        with self.assertRaises(SystemExit): voice.main()
                    self.assertEqual(calls, [False])
                finally:
                    sys.argv = old_argv
            finally:
                os.chdir(old_cwd); voice.__file__ = old_file
        print('CHECK PASS: production split call uses soft fallback; explicit offline audio remains strict')

    def test_ctc_runtime_error_uses_best_effort_without_another_voice_request(self):
        class FakeEngine:
            def __init__(self, _path): pass
            def check_texts(self, _texts): return True
            def load(self): return True
            def analyze(self, *_args): raise RuntimeError('synthetic alignment failure')
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root=pathlib.Path(tmp); work=root/'one_call_voice'/'fp'; work.mkdir(parents=True)
            story={'id':'RV_TEST','cards':[{'vo':'पहिलो विवरण।'},{'vo':'दोस्रो विवरण।'}]}
            texts=[c['vo'] for c in story['cards']]
            calls=[]
            for half in (1,):
                folder=work/('half%d'%half);folder.mkdir()
                write_wav(folder/'master.wav',[int(5000*math.sin(2*math.pi*180*i/8000)) for i in range(16000)])
                (folder/'response_metadata.json').write_text('{"finish_reasons":["STOP"]}',encoding='utf-8')
            master=work/'joined.wav'
            with mock.patch.object(km_ctc,'Engine',FakeEngine), mock.patch.object(voice,'generate',side_effect=lambda *a,**k:calls.append(a)):
                # One-card story means the second half is intentionally omitted.
                pass
            # Use a one-card story to exercise the generic CTC catch without any Gemini call.
            story={'id':'RV_TEST','cards':[{'vo':'पहिलो विवरण।'}]}; texts=[story['cards'][0]['vo']]
            with mock.patch.object(km_ctc,'Engine',FakeEngine), mock.patch.object(voice,'generate',side_effect=lambda *a,**k:calls.append(a)):
                cuts=voice.build_two_halves(story,texts,master,work,root)
            self.assertEqual(cuts,[]); self.assertEqual(calls,[]); self.assertTrue(master.is_file())
        print('CHECK PASS: unexpected CTC errors soften to audio split without a voice request')

    def test_missing_card_recovery_failure_keeps_original_half_and_continues(self):
        class FakeEngine:
            def __init__(self, _path): self.calls=0
            def check_texts(self, _texts): return True
            def load(self): return True
            def analyze(self, _audio, texts, _cache):
                self.calls+=1
                if self.calls==1:
                    return {'present_indices':[0],'missing_indices':[1],'cuts_sec':[],
                            'best_effort':False}
                return {'present_indices':[0,1],'missing_indices':[],'cuts_sec':[1.0],
                        'best_effort':False}
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root=pathlib.Path(tmp);work=root/'one_call_voice'/'fp';work.mkdir(parents=True)
            texts=['पहिलो समाचार विवरण।','दोस्रो समाचार विवरण।',
                   'तेस्रो समाचार विवरण।','चौथो समाचार विवरण।']
            story={'id':'RV_TEST','cards':[{'vo':t,'voice_tone':'neutral'} for t in texts]}
            for half in (1,2):
                folder=work/('half%d'%half);folder.mkdir()
                samples=[int(6000*math.sin(2*math.pi*170*i/8000)) for i in range(16000)]
                write_wav(folder/'master.wav',samples)
                (folder/'response_metadata.json').write_text('{"finish_reasons":["STOP"]}',encoding='utf-8')
            master=work/'joined.wav'; calls=[]
            with mock.patch.object(km_ctc,'Engine',FakeEngine), \
                 mock.patch.object(voice,'generate',side_effect=voice.Stop('synthetic verified no-audio response')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                result=voice.build_two_halves(story,texts,master,work,root,recover_missing=True)
            self.assertEqual(len(result),3)
            self.assertTrue(master.is_file())
            for half in (1,2):
                cards=work/('half%d'%half)/'cards'
                self.assertTrue((cards/'c01.wav').is_file())
                self.assertTrue((cards/'c02.wav').is_file())
            self.assertIn('isolated-card recovery did not complete',output.getvalue())
        print('CHECK PASS: failed isolated-card recovery notes and keeps the original approved half')

    def test_valid_sample_rate_mismatch_can_be_resampled(self):
        source=array.array('h',[0,1000,2000,1000,0])
        converted=voice._resample_pcm16(source,8000,16000)
        self.assertEqual(len(converted),10)
        self.assertEqual(converted[0],source[0])
        self.assertEqual(converted[-1],source[-1])
        self.assertTrue(all(-32768<=sample<=32767 for sample in converted))
        print('CHECK PASS: differing valid sample rates use bounded PCM resampling rather than a quality stop')


class ApprovedLayoutTests(unittest.TestCase):
    def test_converter_failure_keeps_existing_valid_approved_story(self):
        make_reel=importlib.import_module('make_reel')
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root=pathlib.Path(tmp); (root/'stories').mkdir(); (root/'inbox'/'RV_TEST').mkdir(parents=True)
            story={'id':'RV_TEST','cards':[{'vo':'approved narration','voice_tone':'neutral'}]}
            path=root/'stories'/'RV_TEST.json'; original=json.dumps(story);path.write_text(original,encoding='utf-8')
            old=make_reel.ROOT;make_reel.ROOT=root
            try:
                with mock.patch.object(make_reel,'run',return_value=types.SimpleNamespace(returncode=1,stdout='',stderr='synthetic')):
                    self.assertTrue(make_reel.ensure_layout('RV_TEST',always=True))
                self.assertEqual(path.read_text(encoding='utf-8'),original)
            finally:make_reel.ROOT=old
        print('CHECK PASS: failed converter refresh notes and keeps the saved approved narration')


class TimingFallbackTests(unittest.TestCase):
    def test_stale_alignment_is_ignored_and_estimated_timing_is_written(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root=pathlib.Path(tmp); pub=root/'public'; (pub/'voice_in').mkdir(parents=True)
            story_path=root/'story.json'; story={'id':'RV_TEST','cards':[{'vo':'नमुना समाचार।'}]}
            story_path.write_text(json.dumps(story,ensure_ascii=False),encoding='utf-8')
            (pub/'voice_in'/'c01.wav').write_bytes(b'synthetic source audio')
            (pub/'aligned_words.json').write_text(json.dumps({'story_id':'RV_TEST','narration_sha256':'stale','cards':[]}),encoding='utf-8')
            (pub/'voice').mkdir(); (pub/'voice'/'cache.json').write_text('{broken',encoding='utf-8')
            class FakeResult:
                returncode=0; stderr=''; stdout='1.0'
            def fake_run(cmd,*_args,**_kwargs):
                if cmd[0]=='ffmpeg':pathlib.Path(cmd[-1]).write_bytes(b'synthetic converted wav')
                return FakeResult()
            old_argv=sys.argv[:]
            try:
                sys.argv=['tts.py',str(story_path),str(pub)]
                with mock.patch.dict(sys.modules,{'edge_tts':types.SimpleNamespace()}), \
                     mock.patch('subprocess.run',side_effect=fake_run), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    runpy.run_path(str(ROOT/'scripts'/'tts.py'),run_name='__main__')
                timing=json.loads((pub/'timing.json').read_text(encoding='utf-8'))
                self.assertTrue(timing['cards'][0]['words'])
                self.assertIn('TIMING NOTE',output.getvalue())
                self.assertIn('voice timing cache is unreadable',output.getvalue())
            finally:sys.argv=old_argv
        print('CHECK PASS: stale word alignment adds a note and uses estimated timing')

    def test_silence_trim_fallback_keeps_full_supplied_audio(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root=pathlib.Path(tmp); pub=root/'public'; (pub/'voice_in').mkdir(parents=True)
            story_path=root/'story.json'; story={'id':'RV_TEST','cards':[{'vo':'नमुना समाचार।'}]}
            story_path.write_text(json.dumps(story,ensure_ascii=False),encoding='utf-8')
            (pub/'voice_in'/'c01.wav').write_bytes(b'synthetic source audio')
            class FakeResult:
                returncode=0; stderr=''
                def __init__(self,stdout):self.stdout=stdout
            ffprobes=iter(['0.0','1.0']); commands=[]
            def fake_run(cmd,*_args,**_kwargs):
                commands.append(cmd)
                if cmd[0]=='ffmpeg':pathlib.Path(cmd[-1]).write_bytes(b'synthetic converted wav')
                if cmd[0]=='ffprobe':return FakeResult(next(ffprobes))
                return FakeResult('')
            old_argv=sys.argv[:]
            try:
                sys.argv=['tts.py',str(story_path),str(pub)]
                with mock.patch.dict(sys.modules,{'edge_tts':types.SimpleNamespace()}), \
                     mock.patch('subprocess.run',side_effect=fake_run), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    runpy.run_path(str(ROOT/'scripts'/'tts.py'),run_name='__main__')
                timing=json.loads((pub/'timing.json').read_text(encoding='utf-8'))
                ffmpeg=[cmd for cmd in commands if cmd[0]=='ffmpeg']
                self.assertEqual(len(ffmpeg),2)
                self.assertIn('silenceremove',ffmpeg[0][ffmpeg[0].index('-af')+1])
                self.assertNotIn('silenceremove',ffmpeg[1][ffmpeg[1].index('-af')+1])
                self.assertEqual(timing['cards'][0]['ms'],1000)
                self.assertIn('VOICE NOTE',output.getvalue())
            finally:sys.argv=old_argv
        print('CHECK PASS: empty silence-trim output retries processing without trimming source audio')


if __name__ == '__main__':
    unittest.main(verbosity=2)
