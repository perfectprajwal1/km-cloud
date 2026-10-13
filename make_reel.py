#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command reel launcher. Voice auto-accept uses acoustic checks only, not human listening.
v5.4: no-arg run makes ALL unfinished inbox stories (oldest first, max 5 per run), not just new Sheet rows; done.txt now means uploaded to Drive, so a story whose upload failed is simply made again next run."""
import json,os,re,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PY=sys.executable
NPM='npm.cmd' if sys.platform.startswith('win') else 'npm'
def run(cmd):
    print('> '+' '.join(str(x) for x in cmd),flush=True)
    r=subprocess.run(cmd,cwd=str(ROOT),env={**os.environ,'KM_REQUIRE_VOICES':'1'},capture_output=True,text=True,encoding='utf-8',errors='replace')
    if r.stdout:print(r.stdout,end='',flush=True)
    if r.stderr:print(r.stderr,end='',flush=True)
    return r

def valid_story(rid):
    p=ROOT/'stories'/(rid+'.json')
    data=json.loads(p.read_text(encoding='utf-8-sig'))
    if data.get('id')!=rid or not isinstance(data.get('cards'),list) or not data['cards']:raise ValueError('story ID/cards mismatch')
    if any(not isinstance(c.get('vo'),str) or not c['vo'].strip() for c in data['cards']):raise ValueError('empty narration')
    return data

def ensure_layout(rid,always=False):
    p=ROOT/'stories'/(rid+'.json');old=valid_story(rid) if p.exists() else None
    if old is not None and not always and 'selection' not in old:
        print('Keeping existing pre-selector story unchanged.',flush=True);return True
    backup=None
    if old is not None:
        backup=ROOT/'launcher_backups'/(rid+'_'+str(time.time_ns()));backup.mkdir(parents=True)
        for f in (p,p.with_name(rid+'.clips.json')):
            if f.exists():shutil.copy2(f,backup/f.name)
        print('Story backup: '+str(backup),flush=True)
    r=run([PY,'scripts/script_to_story.py','inbox/'+rid])
    try:
        if r.returncode:raise ValueError('converter stopped; see output above')
        new=valid_story(rid)
        if 'selection' in new:raise ValueError('converter still uses selection; install the yesterday restore first')
        if old is not None:
            identity=lambda s:[(c['vo'],c.get('voice_tone','neutral')) for c in s['cards']]
            if identity(new)!=identity(old):raise ValueError('conversion changed narration/tones; original JSON restored, voice not run')
    except Exception as e:
        if backup:
            for f in backup.iterdir():shutil.copy2(f,ROOT/'stories'/f.name)
        print('STOP: '+str(e),flush=True);return False
    return True


def restore_cached_voice(rid):
    from scripts.gemini_voice import MODEL,VOICE
    import hashlib
    story=valid_story(rid)
    texts=[str(c.get('vo','')).strip() for c in story['cards']]
    tones=[c.get('voice_tone','neutral') for c in story['cards']]
    fingerprint=hashlib.sha256(json.dumps([texts,tones,MODEL,VOICE,'two_halves_v1'],ensure_ascii=False).encode()).hexdigest()[:20]
    work=ROOT/'one_call_voice'/fingerprint
    receipt=work/'installed_reviewed.json'
    if not receipt.exists():return
    records=json.loads(receipt.read_text(encoding='utf-8'))
    if len(records)!=len(texts):raise ValueError('saved voice receipt card count mismatch; no voice request')
    for item in records:
        if not re.fullmatch(r'c[0-9]+\.wav',item.get('name','')):raise ValueError('invalid saved card name')
        src=work/'cards'/item['name']
        if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('saved voice card hash mismatch; no voice request')
    dest=ROOT/'public'/'voice_in';dest.mkdir(parents=True,exist_ok=True)
    for f in dest.glob('c*.wav'):f.unlink()
    # Alignment is audio-specific. The renderer recomputes it from these cards.
    for name in ('aligned_words.json','alignment_report.json'):
        (ROOT/'public'/name).unlink(missing_ok=True)
    for item in records:shutil.copy2(work/'cards'/item['name'],dest/item['name'])
    print('Restored exact-script cached voice cards; hashes verified. No new voice request.',flush=True)

def voice_and_render(rid,recover=False):
    restore_cached_voice(rid)
    auto_path=None
    rel='stories/'+rid+'.json'
    r=run([PY,'scripts/gemini_voice.py',rel]+(['--recover-missing'] if recover else []))
    if r.returncode==3:
        matches=re.findall(r'^STAGED CARDS:\s*(.+)$',r.stdout,re.M)
        if not matches:
            print('STOP: review required but staged cards path was not reported. No install/render.',flush=True);return 3
        path=Path(matches[-1].strip()).resolve()
        base=(ROOT/'one_call_voice').resolve()
        if not path.is_relative_to(base) or path.name!='cards' or not path.is_dir():
            print('STOP: invalid staged cards folder. No install/render.',flush=True);return 3
        # Exit 3 proves the voice script completed its acoustic split checks,
        # not that a human heard or verified every word. No retry loop.
        auto_path=path
        r=run([PY,'scripts/gemini_voice.py',rel,'--install-reviewed'])
    if r.returncode:
        print('STOP: voice step stopped. Saved audio/attempt markers kept; no automatic retry or render.',flush=True);return r.returncode
    r=run([NPM,'run','reel','--',rel])
    if r.returncode:print('STOP: render stopped; saved voice kept.');return r.returncode
    out=ROOT/'out'/(rid+'.mp4')
    if not out.is_file() or out.stat().st_size==0:print('STOP: renderer output missing/empty.');return 2
    print('\nREADY: '+str(out),flush=True)
    if auto_path:print('Voice auto-accepted from acoustic checks only, not human-heard. Staged cards: '+str(auto_path),flush=True)
    return 0

def inbox_ids():
    p=ROOT/'inbox'
    return {d.name for d in p.iterdir() if d.is_dir() and re.fullmatch(r'[A-Za-z0-9_-]+',d.name)} if p.exists() else set()

def main():
    args=sys.argv[1:]
    if len(args)>1 or (args and not re.fullmatch(r'[A-Za-z0-9_-]+',args[0])):print('Use: py make_reel.py [REVIEW_ID]');return 2
    dp=ROOT/'out'/'done.txt'
    done=set(dp.read_text(encoding='utf-8').split()) if dp.exists() else set()
    if args and args[0] in done:
        print('Already in Drive on latest saved state: '+args[0]+'. Skipping render.');return 0
    if args:ids=args
    else:
        r=run([PY,'producer.py','--once'])
        if r.returncode:return r.returncode
        dp=ROOT/'out'/'done.txt';done=set()
        if dp.exists():done={l.strip() for l in dp.read_text(encoding='utf-8').splitlines() if l.strip()}
        open_ids=[d for d in sorted(inbox_ids()) if d not in done and not d.startswith('SAMPLE-')]
        ids=open_ids[:5]
        if not ids:print('No newly approved row found.');return 0
        if len(open_ids)>5:print('Batch cap 5: '+str(len(open_ids)-5)+' more stories stay for the next run.',flush=True)
    for rid in ids:
        print('SELECTED ONLY: '+rid,flush=True)
        if not ensure_layout(rid,always=True):return 2
        code=voice_and_render(rid,recover=True)
        if code:return code
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except KeyboardInterrupt:print('Stopped. Saved audio and story backups kept.');sys.exit(3)
    except Exception as e:print('STOP: '+str(e)+' Saved audio and attempt markers kept.');sys.exit(2)
