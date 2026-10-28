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
    child_env={**os.environ,'KM_REQUIRE_VOICES':'1'}
    # Artifact read permission is only needed by this launcher, never by the
    # Gemini, converter, or renderer subprocesses.
    child_env.pop('GH_TOKEN',None)
    r=subprocess.run(cmd,cwd=str(ROOT),env=child_env,capture_output=True,text=True,encoding='utf-8',errors='replace')
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
        if old is not None:
            identity=lambda s:[(c['vo'],c.get('voice_tone','neutral')) for c in s['cards']]
            if identity(new)!=identity(old):raise ValueError('conversion changed narration/tones; original JSON restored, voice not run')
    except Exception as e:
        if backup:
            for f in backup.iterdir():shutil.copy2(f,ROOT/'stories'/f.name)
            print('NOTE: converter refresh did not complete safely ('+type(e).__name__+'); using the existing valid approved story and preserving its narration.',flush=True)
            return True
        print('STOP: '+str(e),flush=True);return False
    return True


def restore_cached_voice(rid):
    from scripts.gemini_voice import MODEL,VOICE,cached_voice_sync_status
    import hashlib
    story=valid_story(rid)
    texts=[str(c.get('vo','')).strip() for c in story['cards']]
    tones=[c.get('voice_tone','neutral') for c in story['cards']]
    fingerprint=hashlib.sha256(json.dumps([texts,tones,MODEL,VOICE,'two_halves_v1'],ensure_ascii=False).encode()).hexdigest()[:20]
    work=ROOT/'one_call_voice'/fingerprint
    receipt=work/'installed_reviewed.json'
    if not receipt.exists():return
    reusable,reason=cached_voice_sync_status(work,len(texts))
    if not reusable:
        print('NOTE: cached voice clips not restored (%s); the normal voice path will rebuild line-to-card mapping.'%reason,flush=True)
        return
    try:
        records=json.loads(receipt.read_text(encoding='utf-8'))
        if not isinstance(records,list) or len(records)!=len(texts):raise ValueError('saved voice receipt card count mismatch')
        expected={'c%02d.wav'%(i+1) for i in range(len(texts))}
        names=[item.get('name') for item in records if isinstance(item,dict)]
        if len(names)!=len(texts) or set(names)!=expected:raise ValueError('saved voice receipt names mismatch')
        for item in records:
            if not isinstance(item,dict) or not re.fullmatch(r'c[0-9]+\.wav',item.get('name','')):raise ValueError('invalid saved card name')
            src=work/'cards'/item['name']
            if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=item.get('sha256'):
                raise ValueError('saved voice card hash mismatch')
    except Exception as e:
        print('NOTE: saved voice receipt is uncertain (%s); retained master audio will be split again if available.'%type(e).__name__,flush=True)
        return
    dest=ROOT/'public'/'voice_in';dest.mkdir(parents=True,exist_ok=True)
    for f in dest.glob('c*.wav'):f.unlink()
    # Alignment is audio-specific. The renderer recomputes it from these cards.
    for name in ('aligned_words.json','alignment_report.json'):
        (ROOT/'public'/name).unlink(missing_ok=True)
    for item in records:shutil.copy2(work/'cards'/item['name'],dest/item['name'])
    print('Restored exact-script cached voice cards; hashes verified. No new voice request.',flush=True)

def commit_selection_history(rid):
    try:
        r2=subprocess.run([PY,'scripts/km_selection.py','commit','stories/'+rid+'.json','out/'+rid+'.mp4'],cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
        print((r2.stdout or '').strip() or ('NOTE: variety history not updated: '+(r2.stderr or '').strip()[-200:]),flush=True)
    except Exception as e:print('NOTE: variety history not updated ('+str(e)[:120]+'); reel is fine.',flush=True)

def voice_and_render(rid,recover=False):
    from scripts.km_artifacts import valid_mp4
    out=ROOT/'out'/(rid+'.mp4')
    if valid_mp4(out):
        print('REUSING saved rendered mp4 for '+rid+'; skipping voice generation and render.',flush=True)
        commit_selection_history(rid)
        return 0
    restore_cached_voice(rid)
    auto_path=None
    rel='stories/'+rid+'.json'
    voice_args=[PY,'scripts/gemini_voice.py',rel]
    if recover:voice_args.extend(['--recover-missing','--retry-verified-no-audio'])
    r=run(voice_args)
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
    if not valid_mp4(out):print('STOP: renderer output is not a complete MP4.');return 2
    print('\nREADY: '+str(out),flush=True)
    # Variety history: counted only now, after a real, non-empty render.
    commit_selection_history(rid)
    if auto_path:print('Voice auto-accepted from acoustic checks only, not human-heard. Staged cards: '+str(auto_path),flush=True)
    return 0

def inbox_ids():
    p=ROOT/'inbox'
    return {d.name for d in p.iterdir() if d.is_dir() and re.fullmatch(r'[A-Za-z0-9_-]+',d.name)} if p.exists() else set()

def pending_ids(limit=5):
    dp=ROOT/'out'/'done.txt'
    done=set(dp.read_text(encoding='utf-8').split()) if dp.exists() else set()
    folders=[ROOT/'inbox'/sid for sid in inbox_ids() if sid not in done and not sid.startswith('SAMPLE-')]
    folders.sort(key=lambda p:(p.stat().st_mtime_ns,p.name))
    return [p.name for p in folders[:limit]]

def process_stories(ids,recover=False):
    """Try every selected approved story; one failure never exits the batch loop."""
    prepared=[];failed=[];tea={}
    for rid in ids:
        print('SELECTED ONLY: '+rid,flush=True)
        try:
            from scripts import km_tea
            tea_path=km_tea.package_path(rid)
            if tea_path:
                tea[rid]=km_tea.prepare(rid,tea_path)
                prepared.append(rid)
            elif ensure_layout(rid,always=True):prepared.append(rid)
            else:failed.append(rid)
        except Exception as e:
            failed.append(rid)
            print('STORY FAILED (continuing queue): '+rid+' | layout '+type(e).__name__+': '+str(e)[:220],flush=True)
    if prepared:
        try:
            from scripts.km_artifacts import restore_pending,valid_mp4
            stories={rid:valid_story(rid) for rid in prepared if not valid_mp4(ROOT/'out'/(rid+'.mp4'))}
            if stories:restore_pending(stories)
        except Exception as e:
            # Artifact lookup is an optimization. A normal render remains the fallback.
            print('NOTE: reusable artifact lookup failed softly ('+type(e).__name__+'); rendering any missing mp4.',flush=True)
    for rid in prepared:
        try:
            if rid in tea:
                code=km_tea.render(rid,tea[rid])
            else:
                code=voice_and_render(rid,recover=recover)
            if code:
                failed.append(rid)
                print('STORY FAILED (continuing queue): '+rid+' | pipeline exit '+str(code),flush=True)
        except Exception as e:
            failed.append(rid)
            print('STORY FAILED (continuing queue): '+rid+' | '+type(e).__name__+': '+str(e)[:220],flush=True)
    succeeded=[rid for rid in prepared if rid not in failed]
    print('BATCH COMPLETE: %s succeeded; %s failed.'%(len(succeeded),len(failed)),flush=True)
    if failed:print('FAILED STORY IDS: '+', '.join(dict.fromkeys(failed)),flush=True)
    return 1 if failed else 0

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
        producer_code=r.returncode
        if producer_code:print('NOTE: approval fetch returned exit %s; queued inbox stories will still be processed.'%producer_code,flush=True)
        open_ids=pending_ids(limit=100000)
        ids=open_ids[:5]
        if not ids:
            if producer_code:return producer_code
            print('No newly approved row found.');return 0
        if len(open_ids)>5:print('Batch cap 5: '+str(len(open_ids)-5)+' more stories stay for the next run.',flush=True)
        batch_code=process_stories(ids,recover=True)
        return batch_code or producer_code
    return process_stories(ids,recover=True)

if __name__=='__main__':
    try:sys.exit(main())
    except KeyboardInterrupt:print('Stopped. Saved audio and story backups kept.');sys.exit(3)
    except Exception as e:print('STOP: '+str(e)+' Saved audio and attempt markers kept.');sys.exit(2)
