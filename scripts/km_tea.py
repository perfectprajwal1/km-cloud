#!/usr/bin/env python3
"""Approved tea packages use the normal KM delivery path. No posting here."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
MARKER = '--- PLATFORM PACK (JSON) ---'


def package_path(rid):
    files = sorted((ROOT / 'inbox' / rid).glob('*.txt'))
    if not files:
        return None
    # Match the publisher's exact package selection. Ambiguous tea inputs fail.
    tea = [p for p in files if p.read_text(encoding='utf-8-sig').splitlines()[:1] == ['STYLE: tea']]
    if tea and (len(files) != 1 or tea[0] != files[0]):
        raise ValueError('tea needs exactly one package txt in inbox/' + rid)
    return tea[0] if tea else None


def prepare(rid, path):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', rid):
        raise ValueError('invalid tea ID')
    text = path.read_text(encoding='utf-8-sig')
    if text.splitlines()[:1] != ['STYLE: tea']:
        raise ValueError('tea style marker missing')
    if text.count(MARKER) != 1:
        raise ValueError('tea package needs one platform pack')
    script, raw = text.split(MARKER, 1)
    pack, _ = json.JSONDecoder().raw_decode(raw.lstrip())
    fields = ('youtube_title', 'youtube_description', 'tiktok_caption',
              'instagram_caption', 'facebook_post', 'threads_post', 'linkedin_post')
    if not isinstance(pack, dict) or any(not isinstance(pack.get(k), str) or not pack[k].strip() for k in fields):
        raise ValueError('tea platform captions/title missing')
    if not isinstance(pack.get('hashtags'), list) or any(not isinstance(t, str) for t in pack['hashtags']):
        raise ValueError('tea hashtags must be a list of strings')
    ids = re.findall(r'^ID:\s*(\S+)\s*$', script, re.M)
    if ids != [rid]:
        raise ValueError('tea ID must equal the approved inbox review_id')
    # Reuse the tested renderer's parser, with only the dialogue section.
    import tea_reel
    with tempfile.TemporaryDirectory(prefix='km-tea-parse-') as tmp:
        staged = Path(tmp) / 'script.txt'
        staged.write_text(script, encoding='utf-8')
        try:
            data = tea_reel.parse(staged)
        except SystemExit as exc:
            raise ValueError('invalid tea dialogue') from exc
    if any(i < 0 or i >= len(data['lines']) - 1 for i in data['cards']):
        raise ValueError('tea card line out of range or overlaps final question')
    # Include the exact script and renderer in artifact and voice identities.
    render_hash = hashlib.sha256((ROOT / 'tea_reel.py').read_bytes()).hexdigest()
    identity = hashlib.sha256((script + render_hash).encode('utf-8')).hexdigest()
    story = {'id': rid, 'style': 'tea', 'cards': [
        {'vo': t, 'voice_tone': 'tea:' + speaker + ':' + identity}
        for speaker, t in data['lines']]}
    target = ROOT / 'stories' / (rid + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(story, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'script': script, 'data': data, 'identity': identity, 'story': story}


def render(rid, prepared):
    from scripts.km_artifacts import valid_mp4
    import tea_reel
    final = ROOT / 'out' / (rid + '.mp4')
    restored = ROOT / 'out' / '.km_artifact_restored' / (rid + '.json')
    if restored.exists():
        receipt = json.loads(restored.read_text(encoding='utf-8'))
        from scripts.km_artifacts import narration_fingerprint
        if receipt.get('manifest_verified') is not True or receipt.get('narration_sha256') != narration_fingerprint(prepared['story']):
            final.unlink(missing_ok=True)
            print('Ignoring unverified legacy tea artifact for ' + rid, flush=True)
        restored.unlink()
    if valid_mp4(final):
        print('REUSING saved tea mp4 for ' + rid, flush=True)
        return 0
    # Voice identity excludes visual edits, so timing/card fixes reuse narration.
    voice_spec = json.dumps([prepared['script'], tea_reel.STYLE_PROMPT, tea_reel.VOICES], ensure_ascii=False, sort_keys=True)
    voice_id = hashlib.sha256(voice_spec.encode()).hexdigest()
    cache = ROOT / 'one_call_voice' / ('tea_voice_' + voice_id)
    cache.mkdir(parents=True, exist_ok=True)
    wav = cache / 'master.wav'
    attempted = cache / 'attempt.json'
    if not wav.is_file():
        # Match the exact deployed legacy renderer identity, never a nearby script.
        legacy_id = hashlib.sha256((prepared['script'] + 'e667ec0a79dd6c02794f825efc5c28d97b91737d49354a1bf83289227806830d').encode()).hexdigest()
        legacy = ROOT / 'one_call_voice' / ('tea_' + legacy_id)
        if (legacy / 'master.wav').is_file():
            shutil.copy2(legacy / 'master.wav', wav)
        elif (legacy / 'attempt.json').exists():
            raise RuntimeError('legacy voice attempt exists; no blind new request')
    if not wav.is_file():
        if attempted.exists():
            raise RuntimeError('tea voice was already attempted; inspect saved state before authorizing another call')
        # Validate free alignment dependencies before any new voice request.
        sys.path.insert(0, str(ROOT / 'scripts'))
        from km_ctc import Engine
        Engine(ROOT / 'models' / 'km_nepali_ctc').load()
        # Verify configuration before claiming a voice attempt.
        key_file = ROOT / 'gemini_key.txt'
        if not os.environ.get('TEA_AUDIO') and not os.environ.get('GEMINI_KEY') and (not key_file.is_file() or not key_file.read_text().strip()):
            raise ValueError('tea Gemini key missing on runner; no call attempted')
        attempted.write_text(json.dumps({'story_id': rid, 'identity': prepared['identity']}) + '\n', encoding='utf-8')
        # Test audio is explicit, never a fallback to a paid call.
        if os.environ.get('TEA_AUDIO'):
            shutil.copy2(Path(os.environ['TEA_AUDIO']).resolve(), wav.with_suffix('.tmp.wav'))
        else:
            # KM reel keeps keys in runner-only files, not this step's env.
            previous_key = os.environ.get('GEMINI_KEY')
            if not previous_key:
                os.environ['GEMINI_KEY'] = (ROOT / 'gemini_key.txt').read_text().strip()
            try:
                tea_reel.tts(prepared['data']['lines'], str(wav.with_suffix('.tmp.wav')))
            except SystemExit as exc:
                raise RuntimeError('tea voice call failed; saved attempt blocks blind retries') from exc
            finally:
                if previous_key is None:
                    os.environ.pop('GEMINI_KEY', None)
                else:
                    os.environ['GEMINI_KEY'] = previous_key
        wav.with_suffix('.tmp.wav').replace(wav)
    # Reject a damaged cache without silently generating another voice.
    seconds = tea_reel.dur(str(wav))
    if not 8 <= seconds <= 75:
        raise ValueError('cached tea voice duration is invalid')
    with tempfile.TemporaryDirectory(prefix='km-tea-render-') as tmp:
        tmp = Path(tmp)
        script = tmp / 'script.txt'
        script.write_text(prepared['script'], encoding='utf-8')
        env = dict(os.environ, TEA_AUDIO=str(wav), OUT_DIR=str(tmp), TEA_OUTRO='0')
        # No repository or publisher credentials enter the renderer process.
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_PAT', 'BUFFER_API_KEY', 'GEMINI_KEY', 'GEMINI_KEY2'):
            env.pop(key, None)
        env.pop('TEA_TEST_RELAX', None)
        result = subprocess.run([sys.executable, str(ROOT / 'tea_reel.py'), str(script)], cwd=ROOT, env=env)
        if result.returncode:
            return result.returncode
        source = tmp / (rid + '_tea.mp4')
        if not valid_mp4(source):
            raise ValueError('tea renderer did not create a valid mp4')
        final.parent.mkdir(parents=True, exist_ok=True)
        pending = final.with_suffix('.mp4.tmp')
        shutil.copy2(source, pending)
        pending.replace(final)
        report = tmp / (rid + '_tea_report.txt')
        if report.exists():
            shutil.copy2(report, final.with_suffix('.tea_report.txt'))
    print('READY TEA: ' + str(final), flush=True)
    return 0
