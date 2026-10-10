#!/usr/bin/env python3
"""Two cached Gemini requests per multi-card story, one per half. No unknown-outcome retries.
Run from project root (two requests for multi-card stories):
  py scripts/gemini_voice.py stories/YOUR_STORY.json
Re-split cached audio without a key/request:
  py scripts/gemini_voice.py stories/YOUR_STORY.json --cuts cuts.json
After listening/checking EVERY staged card:
  py scripts/gemini_voice.py stories/YOUR_STORY.json --install-reviewed
Offline fixture (never reads key):
  py scripts/gemini_voice.py stories/YOUR_STORY.json --audio master.wav
cuts.json is a JSON list of N-1 boundary seconds, e.g. [9.6, 19.2, ...].
"""
import difflib,unicodedata,os
import argparse,array,base64,hashlib,json,math,re,shutil,sys,urllib.error,urllib.request,wave
from pathlib import Path
MODEL='gemini-2.5-flash-preview-tts'
VOICE='Sadachbia'
TONE_MAP={'curious': 'Say this in a curious, intrigued tone, like a Nepali news presenter asking a question:', 'excited': 'Say this in an excited, energetic tone, like a Nepali news presenter sharing surprising news:', 'serious': 'Say this in a serious, steady tone, like a Nepali news presenter reporting important facts:', 'neutral': 'Say this in a calm, clear, neutral tone, like a Nepali news presenter:', 'warm': 'Say this in a warm, reassuring tone, like a Nepali news presenter giving helpful advice:', 'thinking': 'Say this in a thoughtful, measured tone, like a Nepali news presenter reflecting:', 'confused': 'Say this in a questioning, puzzled tone, like a Nepali news presenter:', 'sad': 'Say this in a subdued, somber tone, like a Nepali news presenter:', 'shocked': 'Say this in a shocked, startled tone, like a Nepali news presenter reporting a surprising event:', 'proud': 'Say this in a proud, uplifting tone, like a Nepali news presenter sharing a achievement:', 'urgent': 'Say this in an urgent, alert tone, like a Nepali news presenter:', 'neutral_talking': 'Say this in a relaxed, conversational, natural tone, like a friendly Nepali news presenter explaining something simply to a viewer:'}
class Stop(RuntimeError):pass

def read_wav(path):
    with wave.open(str(path),'rb') as w:
        if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getcomptype()!='NONE':raise Stop('Expected mono 16-bit PCM WAV.')
        rate=w.getframerate();values=array.array('h',w.readframes(w.getnframes()))
    if sys.byteorder!='little':values.byteswap()
    if not values:raise Stop('Empty WAV.')
    return rate,values

def write_wav(path,rate,values):
    raw=array.array('h',values)
    if sys.byteorder!='little':raw.byteswap()
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(raw.tobytes())

def pauses(rate,values,threshold_db=-42):
    step=max(1,round(rate*.02));threshold=32768*10**(threshold_db/20);blocks=[]
    for start in range(0,len(values),step):
        chunk=values[start:start+step];rms=math.sqrt(sum(v*v for v in chunk)/max(1,len(chunk)))
        blocks.append((start,min(start+step,len(values)),rms<=threshold))
    gaps=[];start=None
    for a,b,silent in blocks:
        if silent and start is None:start=a
        if not silent and start is not None:gaps.append((start,a));start=None
    if start is not None:gaps.append((start,len(values)))
    return gaps

def norm_token(word):
    return ''.join(ch for ch in unicodedata.normalize('NFC',word).casefold() if unicodedata.category(ch)[0] in ('L','N','M'))

def verified_asr_cuts(rate,values,texts,words):
    """Conservative exact script-word match. Never approve proportional guesses."""
    expected=[norm_token(w) for t in texts for w in t.split() if norm_token(w)]
    heard=[norm_token(w.get('word','')) for w in words if norm_token(w.get('word',''))]
    words=[w for w in words if norm_token(w.get('word',''))]
    if heard!=expected:
        ratio=difflib.SequenceMatcher(None,expected,heard,autojunk=False).ratio()
        raise Stop('Local ASR did not match every script word in order (match %.1f%%). Candidate timing is NOT verified; master retained. Supply reviewed --cuts; ZERO new Gemini requests.'%(ratio*100))
    duration=len(values)/rate;previous=0.0
    for w in words:
        a,b=w.get('start'),w.get('end')
        if not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or not math.isfinite(a) or not math.isfinite(b) or a<previous or b<a or b>duration:
            raise Stop('ASR word timestamps invalid/overlapping; refusing automatic cuts.')
        previous=b
    gaps=[(a/rate,b/rate) for a,b in pauses(rate,values) if (b-a)/rate>=.12]
    cuts=[];count=0
    for text in texts[:-1]:
        count+=len([w for w in text.split() if norm_token(w)])
        left,right=words[count-1]['end'],words[count]['start']
        # Require acoustic silence between the matched ending and next opening.
        safe=[(a,b) for a,b in gaps if a>=left-.06 and b<=right+.06 and a>0 and b<duration]
        if not safe:raise Stop('No verified >=120ms pause at matched card boundary. Keep master; use reviewed --cuts.')
        a,b=max(safe,key=lambda g:g[1]-g[0]);cut=(a+b)/2
        if cuts and cut<=cuts[-1]:raise Stop('ASR boundary order invalid.')
        cuts.append(cut)
    return cuts

def local_asr_words(master,work,model_path):
    model_path=model_path or os.environ.get('KM_ASR_MODEL')
    if not model_path:raise Stop('Short/extra pauses need transcript verification. Supply --asr-model PATH to an already-installed local faster-whisper model, or reviewed --cuts. No model/network download or Gemini retry performed.')
    model_path=Path(model_path).resolve()
    if not model_path.is_dir():raise Stop('Local ASR model folder missing; no download performed.')
    try:from faster_whisper import WhisperModel
    except ImportError:raise Stop('Optional free local ASR engine not installed (faster-whisper). Existing pause splitting/manual cuts still work; no download performed.') from None
    h=hashlib.sha256(Path(master).read_bytes()).hexdigest();cache=work/'local_asr_words.json'
    if cache.exists():
        data=json.loads(cache.read_text(encoding='utf-8'))
        if data.get('master_sha256')==h and data.get('model_path')==str(model_path):return data['words']
    print('Checking cached master with free LOCAL ASR, CPU. No Gemini request or model download.')
    model=WhisperModel(str(model_path),device='cpu',compute_type='int8',local_files_only=True)
    segments,_=model.transcribe(str(master),language='ne',word_timestamps=True,beam_size=5,vad_filter=False,condition_on_previous_text=False)
    words=[{'word':w.word,'start':w.start,'end':w.end} for segment in segments for w in (segment.words or [])]
    cache.write_text(json.dumps({'master_sha256':h,'model_path':str(model_path),'words':words},ensure_ascii=False,indent=2),encoding='utf-8')
    return words

def split_audio(master,texts,dest,cuts=None,asr_model=None):
    rate,values=read_wav(master);duration=len(values)/rate;gaps=pauses(rate,values)
    long=[(a,b) for a,b in gaps if a>0 and b<len(values) and (b-a)/rate>=1.2]
    if cuts is None:
        if len(long)!=len(texts)-1:
            cuts=verified_asr_cuts(rate,values,texts,local_asr_words(master,Path(dest).parent,asr_model))
        else:cuts=[(a+b)/2/rate for a,b in long]
    if len(cuts)!=len(texts)-1 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in cuts):raise Stop('cuts.json needs exactly N-1 finite numbers.')
    if cuts!=sorted(cuts) or any(x<=0 or x>=duration for x in cuts) or len(set(cuts))!=len(cuts):raise Stop('Cuts must be strictly increasing and within master duration.')
    edges=[0]+[round(x*rate) for x in cuts]+[len(values)];dest.mkdir(parents=True,exist_ok=True);report=[]
    # Prepare everything before writing any card. No cut-through-speech silently accepted.
    prepared=[]
    for i,(a,b,text) in enumerate(zip(edges,edges[1:],texts)):
        chunk=values[a:b];local=pauses(rate,chunk)
        lo=local[0][1] if local and local[0][0]==0 else 0
        hi=local[-1][0] if local and local[-1][1]==len(chunk) else len(chunk)
        lo=max(0,lo-round(.06*rate));hi=min(len(chunk),hi+round(.1*rate));trim=chunk[lo:hi]
        seconds=len(trim)/rate
        if seconds<.5:raise Stop('Card %s is empty/too short; check cuts.'%(i+1))
        speech=sum(1 for v in trim if abs(v)>104)/rate
        if speech<.1:raise Stop('Card %s has no detectable speech.'%(i+1))
        # Acoustic duration/energy checks are NOT transcript identity/repeat checks.
        midpoint=edges[i+1]
        if i<len(texts)-1 and not any(g0<=midpoint<=g1 and (g1-g0)/rate>=.12 for g0,g1 in gaps):
            raise Stop('Boundary after card %s is not inside >=120ms silence; refusing likely cut-through-speech.'%(i+1))
        prepared.append(trim)
        tokens=[re.sub(r'[^\w]','',t.casefold()) for t in text.split()]
        repeated=[tokens[j] for j in range(1,len(tokens)) if tokens[j] and tokens[j]==tokens[j-1]]
        report.append({'card':i+1,'expected_text':text,'master_start_sec':round((a+lo)/rate,3),'master_end_sec':round((a+hi)/rate,3),'duration_sec':round(seconds,3),'script_adjacent_repeats':repeated,'spoken_text_verified':False,'spoken_repeat_check':'NOT VERIFIED. Listen for repeats, especially बैठकले. Waveform cannot reliably identify words.'})
    for i,trim in enumerate(prepared):write_wav(dest/f'c{i+1:02d}.wav',rate,trim)
    summary={'master_sha256':hashlib.sha256(Path(master).read_bytes()).hexdigest(),'cuts_sec':cuts,'cards':report,'check_result':'Acoustic cuts/mono PCM/energy checks PASS. Word identity, omissions, order and spoken repeats REQUIRE listening.'}
    (dest/'split_checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary

def definite_key_rejection(code,body):
    """Allowlist only, never surface raw provider bodies or credentials."""
    try:err=json.loads(body).get('error',{})
    except Exception:err={}
    reasons={d.get('reason','') for d in err.get('details',[]) if isinstance(d,dict)}
    if code==429:return 'quota/rate rejection'
    if code==401:return 'authentication rejection'
    if code in (400,403) and reasons & {'API_KEY_INVALID','API_KEY_EXPIRED','API_KEY_SERVICE_BLOCKED','API_KEY_HTTP_REFERRER_BLOCKED','API_KEY_IP_ADDRESS_BLOCKED','API_KEY_ANDROID_APP_BLOCKED','API_KEY_IOS_APP_BLOCKED'}:return 'key invalid/blocked rejection'
    message=str(err.get('message','')).casefold()
    if code in (400,403) and ('api key not valid' in message or 'api key expired' in message or 'api key was reported as leaked' in message):return 'key invalid/blocked rejection'
    return None

def generate(story,texts,master,work,key_file,backup_key=None):
    # Exact same numeric facts, spoken words before any key/request.
    from km_ctc import spoken_form,AlignmentStop
    try:texts=[spoken_form(t)[0] for t in texts]
    except AlignmentStop as e:raise Stop(str(e)) from None
    # Durable attempt marker BEFORE key/network. A timeout may consume quota: never retry automatically.
    attempt=work/'request_attempt.json'
    if attempt.exists():raise Stop('An earlier request marker blocks this audio. Do not delete it manually. Use the V5 installer --unblock-rejected STORY_ID only for recorded definite rejections; unknown outcomes stay blocked.')

    tone_tags=[str(c.get('voice_tone','neutral')).strip() for c in story['cards']]
    if any(t not in TONE_MAP for t in tone_tags):raise Stop('Unknown voice_tone tag; refusing to guess before quota use.')
    directed='\n\n'.join('[DELIVERY ONLY, DO NOT SPEAK: '+TONE_MAP[tag]+']\n'+text for tag,text in zip(tone_tags,texts))
    prompt=('Read the following Nepali news paragraphs VERBATIM, in order, in a calm clear neutral Nepali news-presenter voice. '
            'Emotion is only in delivery; keep every narration word unchanged and neutral. '
            'Bracketed DELIVERY ONLY lines are stage directions, NOT narration: never speak them. '
            'Follow each paragraph delivery direction, without adding words, explanations or repeated words. '
            'Between EACH paragraph, leave two seconds of complete silence, without speaking the pause instruction. '
            'These pauses separate video cards. Read each narration paragraph below exactly once:\n\n'+directed)
    payload={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseModalities':['AUDIO'],'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':VOICE}}}}}
    # At most one attempt per key. Only a definite HTTP auth/quota/rate
    # rejection allows fallback; timeout/unknown outcome never switches keys.
    state={'model':MODEL,'voice':VOICE,'status':'attempted_once','automatic_retry':False,'attempts':[]}
    answer=None
    candidates=list(dict.fromkeys((key_file,backup_key or key_file.with_name('gemini_key2.txt'))))
    for index,candidate in enumerate(candidates,1):
        slot=2 if candidate.name=='gemini_key2.txt' else 1
        print('Voice request using key file slot %s (%s).'%(slot,candidate.name),flush=True)
        if not candidate.is_file():
            raise Stop('Key file %s missing. No request sent on this key; existing attempt marker retained if a request already happened.'%index)
        key=candidate.read_text(encoding='utf-8').strip()
        if not key:raise Stop('Key file %s empty; nothing sent on this key.'%index)
        state['attempts'].append({'key_slot':slot,'key_file':candidate.name,'status':'attempted'})
        attempt.write_text(json.dumps(state),encoding='utf-8')
        req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+MODEL+':generateContent',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=300) as r:answer=json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:body=e.read(65536).decode('utf-8',errors='replace')
            except Exception:body=''
            reason=definite_key_rejection(e.code,body)
            state['attempts'][-1].update(status='http_rejected' if reason else 'http_failure_no_safe_failover',http_status=e.code,failover_reason=reason)
            attempt.write_text(json.dumps(state),encoding='utf-8')
            if reason and index<len(candidates):
                print('Key slot %s: %s (HTTP %s). Switching once to the other key file; no retry loop.'%(slot,reason,e.code),flush=True)
                continue
            if reason:
                from km_rejection_guard import archive_rejection,GuardStop
                try:backup=archive_rejection(work)
                except GuardStop as guard:raise Stop('Definite rejection, but safe archive refused: '+str(guard)) from None
                raise Stop('Gemini HTTP %s on key slot %s. All attempts definitely rejected; original marker backed up at %s. No retry in this run. Resume later when quota/auth allows. Raw error hidden.'%(e.code,slot,backup)) from None
            raise Stop('Gemini HTTP %s on key slot %s. Outcome not allowlisted; marker kept. No fallback or retry; raw error hidden.'%(e.code,slot)) from None
        except Exception:
            state['attempts'][-1]['status']='unknown_outcome'
            attempt.write_text(json.dumps(state),encoding='utf-8')
            raise Stop('Request failed/timeout on key slot %s. Quota outcome unknown; no fallback or retry. Attempt marker kept.'%slot) from None
        finally:key=None
        print('Voice response received using key slot %s (%s).'%(slot,candidate.name),flush=True)
        state['attempts'][-1]['status']='response_received'
        attempt.write_text(json.dumps(state),encoding='utf-8')
        break
    (work/'response_metadata.json').write_text(json.dumps({'finish_reasons':[c.get('finishReason') for c in answer.get('candidates',[])],'usage':answer.get('usageMetadata',{}),'response_model':answer.get('modelVersion')},indent=2),encoding='utf-8')
    parts=answer.get('candidates',[{}])[0].get('content',{}).get('parts',[])
    audio=[p['inlineData'] for p in parts if p.get('inlineData',{}).get('data')]
    if not audio:raise Stop('Gemini returned no audio. No retry; attempt marker kept.')
    # Preserve decoded result even if unexpected format prevents splitting.
    raw=b''.join(base64.b64decode(p['data'],validate=True) for p in audio)
    (work/'response_audio.bin').write_bytes(raw)
    mime=audio[0].get('mimeType','');m=re.search(r'rate=(\d+)',mime)
    temp=master.with_suffix('.tmp.wav')
    if raw.startswith(b'RIFF') and raw[8:12]==b'WAVE':temp.write_bytes(raw)
    elif mime.startswith('audio/L16'):
        if not m or len(raw)%2:raise Stop('Unexpected PCM response. Raw audio retained; do not regenerate.')
        with wave.open(str(temp),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(int(m.group(1)));w.writeframes(raw)
    else:raise Stop('Unexpected audio format. Raw response retained for offline recovery; no retry.')
    read_wav(temp);temp.replace(master)
    state['status']='audio_saved'
    attempt.write_text(json.dumps(state),encoding='utf-8')

def build_two_halves(story,texts,master,work,project,asr_model=None,cuts=None,recover_missing=False,offline=False):
    """Retain original halves; missing cards have independent durable requests."""
    from km_ctc import Engine,AlignmentStop,digest
    engine=None
    if cuts is None:
        engine=Engine(project/'models'/'km_nepali_ctc')
        try:engine.check_texts(texts);engine.load()
        except AlignmentStop as e:
            (work/'local_stop.json').write_text(json.dumps({'stage':'preflight_before_requests','reason':str(e),'story_id':story.get('id'),'requests_made_by_this_stage':0},ensure_ascii=False,indent=2),encoding='utf-8')
            raise Stop(str(e)) from None
    middle=(len(texts)+1)//2;ranges=[(0,middle),(middle,len(texts))]
    if len(texts)==1:ranges=ranges[:1]
    pieces=[];all_cuts=[];offset=0.0;diagnostics=[]
    # Fetch at most the original two halves; existing cached halves never regenerate.
    for number,(lo,hi) in enumerate(ranges,1):
        folder=work/('half%s'%number);folder.mkdir(exist_ok=True);audio=folder/'master.wav'
        primary=project/('gemini_key.txt' if number==1 else 'gemini_key2.txt')
        backup=project/('gemini_key2.txt' if number==1 else 'gemini_key.txt')
        if not audio.exists():
            if offline:raise Stop('Cached half %s missing. Review/offline mode makes ZERO requests.'%number)
            generate({'cards':story['cards'][lo:hi]},texts[lo:hi],audio,folder,primary,backup)
        metadata_file=folder/'response_metadata.json'
        if not metadata_file.is_file():raise Stop('Half %s metadata missing; cached audio retained.'%number)
        reasons=json.loads(metadata_file.read_text(encoding='utf-8')).get('finish_reasons',[])
        if not reasons or any(r!='STOP' for r in reasons):raise Stop('Half %s finishReason is not STOP. Audio kept; no recovery request.'%number)
    # Analyze every original half before spending on any recovery: a later failed
    # boundary must not be discovered after earlier recovery already used quota.
    fits=[]
    for number,(lo,hi) in enumerate(ranges,1):
        folder=work/('half%s'%number);audio=folder/'master.wav';rate,values=read_wav(audio)
        if cuts is None:
            try:fit=engine.analyze(audio,texts[lo:hi],folder/'ctc')
            except AlignmentStop as e:
                (folder/'local_stop.json').write_text(json.dumps({'stage':'cached_half_alignment','half':number,'reason':str(e),'originals_retained':True},ensure_ascii=False,indent=2),encoding='utf-8')
                raise Stop('Half %s: %s'%(number,e)) from None
            fits.append(fit)
        else:fits.append(None)
    for number,((lo,hi),fit) in enumerate(zip(ranges,fits),1):
        folder=work/('half%s'%number);audio=folder/'master.wav';rate,values=read_wav(audio)
        primary=project/('gemini_key.txt' if number==1 else 'gemini_key2.txt');backup=project/('gemini_key2.txt' if number==1 else 'gemini_key.txt')
        use_audio=audio;use_cuts=None;repair_rows=[]
        if fit is not None:
            if fit['missing_indices']:
                print('MISSING ONLY:',', '.join(str(lo+i+1) for i in fit['missing_indices']))
                present=fit['present_indices']
                split_audio(audio,[texts[lo+i] for i in present],folder/'present_cards',fit['cuts_sec'])
                card_paths={idx:folder/'present_cards'/('c%02d.wav'%(i+1)) for i,idx in enumerate(present)}
                for idx in fit['missing_indices']:
                    global_idx=lo+idx
                    recovery=folder/'missing_cards'/('c%02d'% (global_idx+1));recovery.mkdir(parents=True,exist_ok=True)
                    recovered=recovery/'master.wav'
                    if not recovered.exists():
                        if offline or not recover_missing:
                            raise Stop('Card %s missing. Original halves retained. Run resume_failed.py for missing-card-only recovery; review/offline mode sends nothing.'%(global_idx+1))
                        print('Requesting ONLY missing card %s; original halves kept.'%(global_idx+1))
                        generate({'cards':[story['cards'][global_idx]]},[texts[global_idx]],recovered,recovery,primary,backup)
                    mf=recovery/'response_metadata.json'
                    if not mf.is_file() or json.loads(mf.read_text(encoding='utf-8')).get('finish_reasons')!=['STOP']:
                        raise Stop('Recovered card %s finishReason not STOP. No retry.'%(global_idx+1))
                    try:check=engine.analyze(recovered,[texts[global_idx]],recovery/'ctc')
                    except AlignmentStop as e:raise Stop('Recovered card %s uncertain: %s. No repeat request.'%(global_idx+1,e)) from None
                    if check['missing_indices']:raise Stop('Recovered card still absent. No automatic repeat request.')
                    split_audio(recovered,[texts[global_idx]],recovery/'cards',[])
                    card_paths[idx]=recovery/'cards'/'c01.wav'
                    repair_rows.append({'card':global_idx+1,'master_sha256':digest(recovered)})
                # Restore original STORY order even when omission was in the middle.
                rebuilt=[];local=[]
                for i in range(hi-lo):
                    r,v=read_wav(card_paths[i])
                    if r!=rate:raise Stop('Missing-card sample rate differs. Originals kept; no unsafe append.')
                    if i:local.append((len(rebuilt)+rate)/rate);rebuilt.extend([0]*(rate*2))
                    rebuilt.extend(v)
                use_audio=folder/'repaired_master.wav';temp=folder/'repaired_master.tmp.wav';write_wav(temp,rate,rebuilt);temp.replace(use_audio);use_cuts=local
                (folder/'recovery_receipt.json').write_text(json.dumps({'original_sha256':digest(audio),'missing_cards':repair_rows,'repaired_sha256':digest(use_audio),'cuts_sec':local},indent=2),encoding='utf-8')
            else:use_cuts=fit['cuts_sec']
        else:use_cuts=[v-offset for v in cuts[lo:hi-1]]
        result=split_audio(use_audio,texts[lo:hi],folder/'cards',use_cuts)
        if asr_model:
            # Independent optional validator. Never downloads a model.
            words=local_asr_words(use_audio,folder,asr_model)
            from km_ctc import similarity,letters
            heard=' '.join(w['word'] for w in words)
            ratio=similarity(' '.join(texts[lo:hi]),heard)
            if ratio<.85:raise Stop('Optional Whisper validator disagrees (%.1f%%). Review originals; no retry.'%(ratio*100))
            expected=[norm_token(w) for t in texts[lo:hi] for w in t.split() if norm_token(w)]
            got=[norm_token(w['word']) for w in words if norm_token(w['word'])]
            unexpected=[got[i] for i in range(1,len(got)) if got[i]==got[i-1] and not any(expected[k]==expected[k-1]==got[i] for k in range(1,len(expected)))]
            if unexpected:raise Stop('Optional Whisper detected possible repeated words. Review; no automatic retry.')
        rate,values=read_wav(use_audio);seconds=len(values)/rate
        diagnostics.append({'half':number,'original_master_sha256':digest(audio),'used_master_sha256':digest(use_audio),'seconds':seconds,'ctc':fit,'recovered':repair_rows,'manual_override':cuts is not None,'word_identity_certified':False})
        all_cuts.extend(offset+c for c in result['cuts_sec']);pieces.append((rate,values));offset+=seconds
        if number<len(ranges):all_cuts.append(offset+1);offset+=2
    if len(set(rate for rate,_ in pieces))!=1:raise Stop('Half rates differ; originals kept.')
    rate=pieces[0][0];joined=[]
    for i,(_,values) in enumerate(pieces):
        if i:joined.extend([0]*(rate*2))
        joined.extend(values)
    tmp=work/'two_halves_joined.tmp.wav';write_wav(tmp,rate,joined)
    if master.exists() and digest(master)!=digest(tmp):
        old=work/('retained_joined_'+digest(master)[:16]+'.wav')
        if not old.exists():shutil.copy2(master,old)
    tmp.replace(master)
    (work/'two_half_join.json').write_text(json.dumps({'design':'ctc_missing_v1','half_ranges':ranges,'cuts_sec':all_cuts,'diagnostics':diagnostics,'master_sha256':digest(master),'internal_word_completeness':'CTC provisional, listening review required'},ensure_ascii=False,indent=2),encoding='utf-8')
    return all_cuts

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('story');ap.add_argument('--audio',help='Offline master WAV; never reads key or calls Gemini');ap.add_argument('--cuts');ap.add_argument('--asr-model',help='Optional already-installed faster-whisper model directory, CPU offline only');ap.add_argument('--install-reviewed',action='store_true');ap.add_argument('--recover-missing',action='store_true',help='Recover only confidently absent cards, never unknown outcomes');args=ap.parse_args()
    project=Path(__file__).resolve().parent.parent;story=json.loads(Path(args.story).read_text(encoding='utf-8'));texts=[str(c.get('vo','')).strip() for c in story.get('cards',[])]
    if not texts or any(not t for t in texts):raise Stop('Every card must have nonempty vo.')
    tags=[str(c.get('voice_tone','neutral')).strip() for c in story['cards']]
    if any(tag not in TONE_MAP for tag in tags):raise Stop('Unknown voice_tone. No request made.')
    print('DELIVERY PER CARD:', ', '.join(str(i+1)+' '+tag for i,tag in enumerate(tags)))
    fingerprint=hashlib.sha256(json.dumps([texts,[c.get('voice_tone','neutral') for c in story['cards']],MODEL,VOICE,'two_halves_v1'],ensure_ascii=False).encode()).hexdigest()[:20]
    work=project/'one_call_voice'/fingerprint;work.mkdir(parents=True,exist_ok=True)
    from km_ctc import spoken_form,SP_NUMBER_REVISION
    numeric_targets=[{'original':t,'spoken':spoken_form(t)[0],'mapping':spoken_form(t)[1]} for t in texts]
    (work/'spoken_number_targets.json').write_text(json.dumps({'version':SP_NUMBER_REVISION,'targets':numeric_targets},ensure_ascii=False,indent=2),encoding='utf-8')
    for i,row in enumerate(numeric_targets,1):
        for item in row['mapping']:
            if item.get('note'):print('SPOKEN TARGET NOTE card %s: %s -> %s. %s'%(i,item['original'],item['spoken'],item['note']))
    master=work/'master.wav';dest=work/'cards'
    receipt=work/'installed_reviewed.json';public=project/'public/voice_in'
    if receipt.exists() and not args.audio and not args.cuts and not args.install_reviewed:
        records=json.loads(receipt.read_text(encoding='utf-8'))
        if len(records)!=len(texts) or any(not (public/item['name']).is_file() or hashlib.sha256((public/item['name']).read_bytes()).hexdigest()!=item['sha256'] for item in records):
            raise Stop('Reviewed installation receipt exists but voice files changed/missing. Restore reviewed files or inspect backup; no request made.')
        print('Reviewed voices already installed for this exact script/tones. ZERO Gemini calls. Ready to render.')
        return
    if args.audio:
        src=Path(args.audio).resolve();read_wav(src)
        if master.exists() and master.read_bytes()!=src.read_bytes():raise Stop('Different offline master already cached. Use a separate test directory; refusing overwrite.')
        if src!=master.resolve():shutil.copy2(src,master)
    cuts=json.loads(Path(args.cuts).read_text()) if args.cuts else None
    if not args.audio and cuts is not None and master.exists():
        print('Reviewed manual cuts on retained joined master. ZERO requests; CTC semantic gates bypassed.')
    elif not args.audio:
        cuts=build_two_halves(story,texts,master,work,project,args.asr_model,cuts,args.recover_missing,offline=args.install_reviewed)
    elif cuts is None:
        from km_ctc import Engine,AlignmentStop
        try:
            fit=Engine(project/'models'/'km_nepali_ctc').analyze(master,texts,work/'offline_ctc')
        except AlignmentStop as e:raise Stop(str(e)) from None
        if fit['missing_indices']:raise Stop('Offline audio has missing cards. No keys read or recovery requests in --audio mode.')
        cuts=fit['cuts_sec']
    report=split_audio(master,texts,dest,cuts,args.asr_model)
    print('MASTER KEPT:',master);print('STAGED CARDS:',dest)
    for row in report['cards']:print('card %02d: %.2fs | text/repeats NOT VERIFIED'%(row['card'],row['duration_sec']))
    print('CTC/manual acoustic checks passed. Completeness thresholds are provisional; listen to every staged card for words/repeats before installation. No caption word alignment produced.')
    if args.install_reviewed:
        public=project/'public/voice_in';public.mkdir(parents=True,exist_ok=True)
        backup=work/'previous_voice_in'
        if backup.exists():raise Stop('A previous installation backup exists; refusing overwrite. Check existing voice_in before another installation.')
        backup.mkdir()
        for p in public.glob('c*.wav'):shutil.copy2(p,backup/p.name)
        for p in public.glob('c*.wav'):p.unlink()
        # Audio-specific alignment must never survive a replacement voice installation.
        for name in ['aligned_words.json','alignment_report.json']:
            old=project/'public'/name
            if old.exists():shutil.copy2(old,backup/name);old.unlink()
        for p in dest.glob('c*.wav'):shutil.copy2(p,public/p.name)
        receipt.write_text(json.dumps([{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(public.glob('c*.wav'))]),encoding='utf-8')
        print('Installed reviewed cards in',public,'; previous voices backed up at',backup)
        print('Render directly with npm run reel -- YOUR_STORY.json, or rerun the updated make_reel.py: reviewed receipt prevents a second request.')
    else:
        print('REVIEW REQUIRED: existing voice_in unchanged. Listen, then rerun with --install-reviewed (and the same --audio/--cuts if used). Cached master: ZERO new requests.')
        sys.exit(3)
if __name__=='__main__':
    try:main()
    except Stop as e:print('STOP:',e);sys.exit(2)
    except Exception as e:
        from km_ctc import AlignmentStop
        if isinstance(e,AlignmentStop):print('STOP: '+str(e)+' Originals and attempt markers kept; no automatic retry.')
        else:print('STOP: local processing failed (%s). Originals and attempt markers kept; no automatic retry.'%type(e).__name__)
        sys.exit(2)
