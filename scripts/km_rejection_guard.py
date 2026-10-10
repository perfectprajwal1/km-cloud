"""Offline rejection-marker checks. No keys, provider bodies or network access."""
import hashlib,json,os,time,uuid
from pathlib import Path
MODEL='gemini-2.5-flash-preview-tts'
VOICE='Sadachbia'
class GuardStop(RuntimeError):pass

def validated_rejection(raw):
    try:state=json.loads(raw.decode('utf-8'))
    except Exception:raise GuardStop('Unreadable attempt marker; kept.') from None
    if not isinstance(state,dict) or state.get('model')!=MODEL or state.get('voice')!=VOICE or state.get('status') not in ('attempted_once','definitely_rejected') or state.get('automatic_retry') is not False:
        raise GuardStop('Unrecognized or accepted attempt state; kept.')
    attempts=state.get('attempts')
    if not isinstance(attempts,list) or not 1<=len(attempts)<=2:raise GuardStop('Missing or unrecognized attempt history; kept.')
    slots=set()
    for row in attempts:
        if not isinstance(row,dict):raise GuardStop('Malformed attempt history; kept.')
        slot=row.get('key_slot');code=row.get('http_status');reason=row.get('failover_reason')
        expected={1:'gemini_key.txt',2:'gemini_key2.txt'}
        if type(slot) is not int or slot not in expected or slot in slots or row.get('key_file')!=expected[slot]:raise GuardStop('Unrecognized key-slot history; kept.')
        slots.add(slot)
        allowed={429:'quota/rate rejection',401:'authentication rejection',400:'key invalid/blocked rejection',403:'key invalid/blocked rejection'}
        if row.get('status')!='http_rejected' or type(code) is not int or code not in allowed or reason!=allowed[code]:
            raise GuardStop('Not every attempt is a definite allowlisted rejection; kept. Unknown outcomes never unblock.')
    return state

def archive_rejection(work,expected_raw=None):
    work=Path(work);marker=work/'request_attempt.json'
    raw=marker.read_bytes();state=validated_rejection(raw)
    if expected_raw is not None and raw!=expected_raw:raise GuardStop('Attempt marker changed; kept.')
    # A response artifact means an outcome may have been accepted. Never discard it.
    for name in ('master.wav','master.tmp.wav','response_audio.bin','response_metadata.json'):
        if (work/name).exists():raise GuardStop('Response/audio artifact exists; attempt marker kept for inspection.')
    backup=work/'rejected_attempt_backups'/(str(time.time_ns())+'_'+uuid.uuid4().hex)
    backup.mkdir(parents=True,exist_ok=False)
    receipt={'marker_sha256':hashlib.sha256(raw).hexdigest(),'attempts':state['attempts'],'reason':'all attempts recorded definite rejections','network_calls':0}
    with (backup/'receipt.json').open('w',encoding='utf-8') as f:
        json.dump(receipt,f,indent=2);f.flush();os.fsync(f.fileno())
    if marker.read_bytes()!=raw:raise GuardStop('Attempt marker changed during backup; kept.')
    # Same-filesystem atomic move preserves the original marker as the backup.
    os.replace(marker,backup/'request_attempt.json')
    if (backup/'request_attempt.json').read_bytes()!=raw:raise GuardStop('Backup readback mismatch; stop and inspect backup.')
    return backup

def unblock_story(root,rid):
    import re,wave
    root=Path(root).resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',rid):raise GuardStop('Invalid story ID.')
    path=root/'stories'/(rid+'.json')
    story=json.loads(path.read_text(encoding='utf-8'))
    cards=story.get('cards')
    if story.get('id')!=rid or not isinstance(cards,list) or not cards:raise GuardStop('Story ID/cards mismatch.')
    if any(not isinstance(c,dict) or not isinstance(c.get('vo'),str) or not c['vo'].strip() for c in cards):raise GuardStop('Invalid narration; no cleanup.')
    texts=[c['vo'].strip() for c in cards]
    fingerprint=hashlib.sha256(json.dumps([texts,[c.get('voice_tone','neutral') for c in cards],MODEL,VOICE,'two_halves_v1'],ensure_ascii=False).encode()).hexdigest()[:20]
    base=root/'one_call_voice';work=base/fingerprint
    if not work.is_dir() or work.is_symlink() or base.is_symlink():raise GuardStop('Exact story cache missing or redirected; no cleanup.')
    planned=[];preserved=[]
    for number in range(1,2 if len(cards)==1 else 3):
        folder=work/('half'+str(number))
        if not folder.is_dir() or folder.is_symlink():raise GuardStop('Original half cache missing or redirected; no cleanup.')
        master=folder/'master.wav';marker=folder/'request_attempt.json'
        if master.is_file():
            if master.is_symlink():raise GuardStop('Redirected cached audio; no cleanup.')
            with wave.open(str(master),'rb') as w:
                if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getnframes()==0 or len(w.readframes(w.getnframes()))!=w.getnframes()*2:raise GuardStop('Cached half WAV invalid; no cleanup.')
            metadata=json.loads((folder/'response_metadata.json').read_text(encoding='utf-8'))
            reasons=metadata.get('finish_reasons',[])
            if not reasons or any(x!='STOP' for x in reasons):raise GuardStop('Cached half finish reason uncertain; no cleanup.')
            preserved.append({'half':number,'sha256':hashlib.sha256(master.read_bytes()).hexdigest()});continue
        if not marker.is_file() or marker.is_symlink():raise GuardStop('Missing or redirected attempt marker for uncached half; no cleanup.')
        raw=marker.read_bytes();validated_rejection(raw)
        if any((folder/n).exists() for n in ('master.tmp.wav','response_audio.bin','response_metadata.json')):raise GuardStop('Response artifacts on uncached half; no cleanup.')
        planned.append((folder,raw))
    if not planned:
        print('No rejected uncached half to unblock. Cached originals unchanged. ZERO network calls.');return
    # Validate ALL halves before moving any marker. Never choose a newest story.
    for folder,raw in planned:
        backup=archive_rejection(folder,raw)
        print('Verified rejected marker archived: '+str(backup))
    for row in preserved:
        master=work/('half'+str(row['half']))/'master.wav'
        if hashlib.sha256(master.read_bytes()).hexdigest()!=row['sha256']:raise GuardStop('Cached audio changed concurrently. Stop; do not resume.')
        print('Preserved half '+str(row['half'])+' audio SHA256: '+row['sha256'])
    print('Unblocked ONLY '+rid+'. ZERO network calls. No audio/story/key files changed. Resume later when quota allows; only missing audio may need a request.')
