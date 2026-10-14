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
import argparse,array,base64,hashlib,json,math,re,shutil,sys,time,urllib.error,urllib.request,wave
from pathlib import Path
MODEL='gemini-2.5-flash-preview-tts'
VOICE='Sadachbia'
TONE_MAP={'curious': 'Say this in a curious, intrigued tone, like a Nepali news presenter asking a question:', 'excited': 'Say this in an excited, energetic tone, like a Nepali news presenter sharing surprising news:', 'serious': 'Say this in a serious, steady tone, like a Nepali news presenter reporting important facts:', 'neutral': 'Say this in a calm, clear, neutral tone, like a Nepali news presenter:', 'warm': 'Say this in a warm, reassuring tone, like a Nepali news presenter giving helpful advice:', 'thinking': 'Say this in a thoughtful, measured tone, like a Nepali news presenter reflecting:', 'confused': 'Say this in a questioning, puzzled tone, like a Nepali news presenter:', 'sad': 'Say this in a subdued, somber tone, like a Nepali news presenter:', 'shocked': 'Say this in a shocked, startled tone, like a Nepali news presenter reporting a surprising event:', 'proud': 'Say this in a proud, uplifting tone, like a Nepali news presenter sharing a achievement:', 'urgent': 'Say this in an urgent, alert tone, like a Nepali news presenter:', 'neutral_talking': 'Say this in a relaxed, conversational, natural tone, like a friendly Nepali news presenter explaining something simply to a viewer:'}
class Stop(RuntimeError):pass

def _write_json_atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    temp.replace(path)

def read_wav(path):
    with wave.open(str(path),'rb') as w:
        if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getcomptype()!='NONE':raise Stop('Expected mono 16-bit PCM WAV.')
        rate=w.getframerate();values=array.array('h',w.readframes(w.getnframes()))
    if sys.byteorder!='little':values.byteswap()
    if not values:raise Stop('Empty WAV.')
    if rate<=0:raise Stop('WAV has an invalid sample rate.')
    return rate,values

def write_wav(path,rate,values):
    raw=array.array('h',values)
    if sys.byteorder!='little':raw.byteswap()
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(raw.tobytes())

def _resample_pcm16(values,source_rate,target_rate):
    """Convert valid mono PCM samples to a common rate without external tools."""
    if source_rate<=0 or target_rate<=0 or not values:raise Stop('Cannot resample empty audio or an invalid sample rate.')
    if source_rate==target_rate:return array.array('h',values)
    output_count=max(1,round(len(values)*target_rate/source_rate))
    out=array.array('h')
    for index in range(output_count):
        position=index*source_rate/target_rate
        left=min(int(position),len(values)-1);right=min(left+1,len(values)-1)
        fraction=position-left
        value=round(values[left]+(values[right]-values[left])*fraction)
        out.append(max(-32768,min(32767,value)))
    return out

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

def _duration_weighted_cuts(rate,values,texts):
    """Last-resort sample-preserving cuts with at least one sample per card."""
    count=len(texts);sample_count=len(values)
    if count<1 or rate<=0 or sample_count<count:
        raise Stop('Not enough valid audio samples to give every approved card audio.')
    weights=[]
    for text in texts:
        weight=sum(1 for ch in unicodedata.normalize('NFC',str(text))
                   if unicodedata.category(ch)[0] in ('L','M','N'))
        weights.append(max(1,weight))
    total=sum(weights);cumulative=0;previous=0;cuts=[]
    for index,weight in enumerate(weights[:-1]):
        cumulative+=weight;remaining=count-index-1
        ideal=round(sample_count*cumulative/total)
        sample=max(previous+1,min(ideal,sample_count-remaining))
        cuts.append(sample/rate);previous=sample
    return cuts

def _soft_cuts(rate,values,texts):
    """Try the audio-aware local splitter, then use bounded duration weights."""
    try:
        from km_ctc import soft_cut_points
        cuts=soft_cut_points(values,rate,texts)
        if (len(cuts)==len(texts)-1 and
                all(isinstance(x,(int,float)) and math.isfinite(x) for x in cuts) and
                cuts==sorted(cuts) and len(set(cuts))==len(cuts) and
                all(0<x<len(values)/rate for x in cuts)):
            return cuts
    except Exception:
        pass
    return _duration_weighted_cuts(rate,values,texts)

def _valid_fit(fit,count):
    """Reject malformed CTC metadata as uncertain before it can authorize repair."""
    if not isinstance(fit,dict):return False
    present=fit.get('present_indices');missing=fit.get('missing_indices');cuts=fit.get('cuts_sec')
    if not isinstance(present,list) or not isinstance(missing,list) or not isinstance(cuts,list):return False
    if not present:return False
    indices=present+missing
    if any(isinstance(i,bool) or not isinstance(i,int) or i<0 or i>=count for i in indices):return False
    if len(set(indices))!=count or set(indices)!=set(range(count)):return False
    if len(set(present))!=len(present) or len(set(missing))!=len(missing):return False
    if len(cuts)!=max(0,len(present)-1):return False
    return all(isinstance(x,(int,float)) and math.isfinite(x) for x in cuts)

def cached_voice_sync_status(work,card_count):
    """Tell launchers whether an installed voice receipt has a durable sync plan.

    Old receipts from estimated/soft multi-line splits do not prove that each
    clip belongs to the line on screen. Force those through the current sync
    path once; known CTC cuts and separately requested one-line clips are safe
    to restore without another provider call.
    """
    path=Path(work)/'two_half_join.json'
    if not path.is_file():return False,'saved line-to-audio sync plan is missing'
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        diagnostics=data.get('diagnostics') if isinstance(data,dict) else None
        expected=1 if card_count<=1 else 2
        if not isinstance(diagnostics,list) or len(diagnostics)!=expected:
            return False,'saved line-to-audio sync plan is incomplete'
        methods={'ctc_boundaries','ctc_missing_recovered','isolated_per_card','manual_cuts'}
        for row in diagnostics:
            if not isinstance(row,dict) or row.get('sync_method') not in methods:
                return False,'saved voice used an unverified estimated split'
            count=row.get('card_count')
            if isinstance(count,bool) or not isinstance(count,int) or count<1:
                return False,'saved sync plan has no card count'
            half=row.get('half')
            if isinstance(half,bool) or not isinstance(half,int) or half<1:
                return False,'saved sync plan has no half identifier'
            half_folder=Path(work)/('half%s'%half);source_master=half_folder/'master.wav'
            if (not source_master.is_file() or
                    hashlib.sha256(source_master.read_bytes()).hexdigest()!=row.get('original_master_sha256')):
                return False,'saved source audio no longer matches its sync plan'
            method=row['sync_method']
            ctc=row.get('ctc')
            if method=='isolated_per_card':
                clips=row.get('recovered')
                if not isinstance(clips,list) or len(clips)!=count:
                    return False,'saved isolated-card audio list is incomplete'
                for clip in clips:
                    if not isinstance(clip,dict) or isinstance(clip.get('card'),bool) or not isinstance(clip.get('card'),int):
                        return False,'saved isolated-card entry is malformed'
                    if clip.get('source')=='single-line half':path=source_master
                    else:path=half_folder/'isolated_cards'/('c%02d'%clip['card'])/'master.wav'
                    if (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=clip.get('master_sha256')):
                        return False,'saved isolated-card audio no longer matches its sync plan'
            elif method=='ctc_boundaries':
                if (not isinstance(ctc,dict) or ctc.get('best_effort') is True or
                        ctc.get('partial_missing_indices') or ctc.get('missing_indices') or
                        len(ctc.get('present_indices',[]))!=count or
                        len(ctc.get('cuts_sec',[]))!=count-1 or
                        ctc.get('master_sha256')!=row.get('original_master_sha256')):
                    return False,'saved CTC line mapping is incomplete or uncertain'
            elif method=='ctc_missing_recovered':
                if (not isinstance(ctc,dict) or ctc.get('best_effort') is True or
                        len(ctc.get('present_indices',[]))+len(ctc.get('missing_indices',[]))!=count or
                        len(row.get('recovered',[]))!=len(ctc.get('missing_indices',[])) or
                        ctc.get('master_sha256')!=row.get('original_master_sha256')):
                    return False,'saved missing-card repair plan is incomplete'
                for clip in row['recovered']:
                    if not isinstance(clip,dict) or isinstance(clip.get('card'),bool) or not isinstance(clip.get('card'),int):
                        return False,'saved missing-card entry is malformed'
                    path=half_folder/'missing_cards'/('c%02d'%clip['card'])/'master.wav'
                    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=clip.get('master_sha256'):
                        return False,'saved recovered-card audio no longer matches its sync plan'
            elif method=='manual_cuts' and row.get('manual_override') is not True:
                return False,'manual cut receipt is incomplete'
        return True,'saved sync plan is complete'
    except Exception as exc:
        return False,'saved sync plan could not be verified (%s)'%type(exc).__name__

def _isolate_uncertain_half(story,texts,lo,hi,folder,rate,project,primary,backup,offline=False,retry_verified_no_audio=False):
    """Make one durable voice response per line when a combined half is uncertain.

    A line-specific response is inherently assigned to that line. Two seconds
    of silence are inserted between responses, and cuts land at the midpoint
    of those known silences. The approved text and existing voice settings are
    passed through generate() unchanged.
    """
    if hi-lo==1:
        audio=folder/'master.wav';single_rate,samples=read_wav(audio)
        return audio,[],[{'card':lo+1,'master_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),
                          'duration_sec':round(len(samples)/single_rate,3),'source':'single-line half'}]
    cached=[folder/'isolated_cards'/('c%02d'%(idx+1))/'master.wav' for idx in range(lo,hi)]
    if offline and not all(path.is_file() for path in cached):
        print('NOTE: per-card voice recovery skipped in offline review mode; the retained half uses an unverified soft split.',flush=True)
        audio=folder/'master.wav';_,values=read_wav(audio)
        return audio,_soft_cuts(rate,values,texts[lo:hi]),[]
    rows=[];cuts=[];combined=array.array('h')
    silence=array.array('h',[0])*(rate*2)
    for global_idx in range(lo,hi):
        card_folder=folder/'isolated_cards'/('c%02d'%(global_idx+1));card_folder.mkdir(parents=True,exist_ok=True)
        card_master=card_folder/'master.wav'
        if not card_master.is_file() and not offline:
            print('Requesting card %s separately because its combined-half boundary was uncertain.'%(global_idx+1),flush=True)
            generate({'cards':[story['cards'][global_idx]]},[texts[global_idx]],card_master,card_folder,primary,backup,retry_verified_no_audio)
        card_rate,samples=read_wav(card_master)
        if card_rate!=rate:
            print('NOTE: isolated card %s sample rate differs; converting it to the retained half rate.'%(global_idx+1),flush=True)
            samples=_resample_pcm16(samples,card_rate,rate)
        if global_idx>lo:
            cuts.append((len(combined)+rate)/rate)
            combined.extend(silence)
        combined.extend(samples)
        rows.append({'card':global_idx+1,'master_sha256':hashlib.sha256(card_master.read_bytes()).hexdigest(),
                     'duration_sec':round(len(samples)/rate,3)})
    if not combined:raise Stop('No valid isolated card audio is available for the uncertain half.')
    audio=folder/'isolated_master.wav';temp=folder/'isolated_master.tmp.wav'
    write_wav(temp,rate,combined);temp.replace(audio)
    _write_json_atomic(folder/'isolated_recovery_receipt.json',{
        'method':'one_request_per_approved_line','cards':rows,
        'line_to_audio_isolation':'each output clip came from a request containing only its own approved line',
        'cuts_sec':cuts,'master_sha256':hashlib.sha256(audio.read_bytes()).hexdigest()})
    print('NOTE: uncertain combined audio was replaced for this half by separately cached, line-specific clips; no text was changed.',flush=True)
    return audio,cuts,rows

def split_audio(master,texts,dest,cuts=None,asr_model=None,soft_fallback=False,fallback_note='',auto_soft=True,preserve_samples=False):
    """Split an approved narration, turning every alignment doubt into a note.

    The production path preserves all source samples and replaces suspect cuts
    with audio-aware, then duration-weighted cuts. Strict mode is reserved for
    the explicit offline --audio diagnostic command.
    """
    try:
        return _split_audio_strict(master,texts,dest,cuts,asr_model,soft_fallback,fallback_note,preserve_samples)
    except Exception as exc:
        if not auto_soft:raise
        detail=(str(exc).strip() or type(exc).__name__).replace('\n',' ')[:180]
        note='Strict split/alignment check was not conclusive ('+detail+'); all source samples retained in a soft split.'
        print('NOTE: '+note+' Word identity and exact card boundaries are unverified.',flush=True)
        rate,values=read_wav(master)
        if preserve_samples:
            # The cuts came from explicit per-line clips or a previously
            # validated CTC plan. Do not replace them with duration estimates.
            raise
        fallback_cuts=_soft_cuts(rate,values,texts)
        return _split_audio_strict(master,texts,dest,fallback_cuts,None,True,note)

def _split_audio_strict(master,texts,dest,cuts=None,asr_model=None,soft_fallback=False,fallback_note='',preserve_samples=False):
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
        if soft_fallback or preserve_samples:
            # Keep each source sample exactly once. A low-confidence cut may
            # cross speech; trimming here could silently remove part of a word.
            lo=0;hi=len(chunk);trim=chunk
        else:
            lo=local[0][1] if local and local[0][0]==0 else 0
            hi=local[-1][0] if local and local[-1][1]==len(chunk) else len(chunk)
            lo=max(0,lo-round(.06*rate));hi=min(len(chunk),hi+round(.1*rate));trim=chunk[lo:hi]
        seconds=len(trim)/rate
        quality_notes=[]
        if seconds<.5:
            if not soft_fallback and not preserve_samples:raise Stop('Card %s is empty/too short; check cuts.'%(i+1))
            quality_notes.append('audio interval is shorter than 0.5 seconds')
        speech=sum(1 for v in trim if abs(v)>104)/rate
        if speech<.1:
            if not soft_fallback and not preserve_samples:raise Stop('Card %s has no detectable speech.'%(i+1))
            quality_notes.append('speech energy was not detected')
        # Acoustic duration/energy checks are NOT transcript identity/repeat checks.
        midpoint=edges[i+1]
        boundary_ok=i==len(texts)-1 or any(g0<=midpoint<=g1 and (g1-g0)/rate>=.12 for g0,g1 in gaps)
        if i<len(texts)-1 and not boundary_ok and not soft_fallback and not preserve_samples:
            raise Stop('Boundary after card %s is not inside >=120ms silence; refusing likely cut-through-speech.'%(i+1))
        if i<len(texts)-1 and not boundary_ok:quality_notes.append('boundary is not inside detected 120 ms silence')
        if quality_notes:print('NOTE: Card %s: %s; mapped audio retained.'%(i+1,'; '.join(quality_notes)),flush=True)
        prepared.append(trim)
        tokens=[re.sub(r'[^\w]','',t.casefold()) for t in text.split()]
        repeated=[tokens[j] for j in range(1,len(tokens)) if tokens[j] and tokens[j]==tokens[j-1]]
        report.append({'card':i+1,'expected_text':text,'master_start_sec':round((a+lo)/rate,3),'master_end_sec':round((a+hi)/rate,3),'duration_sec':round(seconds,3),'script_adjacent_repeats':repeated,'spoken_text_verified':False,'spoken_repeat_check':'NOT VERIFIED. Listen for repeats, especially बैठकले. Waveform cannot reliably identify words.','soft_fallback':bool(soft_fallback),'sample_preserving':bool(soft_fallback or preserve_samples),'boundary_in_silence':boundary_ok,'quality_notes':quality_notes})
    for i,trim in enumerate(prepared):write_wav(dest/f'c{i+1:02d}.wav',rate,trim)
    summary={'master_sha256':hashlib.sha256(Path(master).read_bytes()).hexdigest(),'cuts_sec':cuts,'cards':report,'soft_fallback':bool(soft_fallback),'sample_preserving':bool(soft_fallback or preserve_samples),'fallback_note':fallback_note if soft_fallback else '', 'check_result':(('SOFT FALLBACK: complete source audio retained and split; word identity and exact card boundaries are unverified. '+fallback_note) if soft_fallback else ('Known line-to-audio cuts used; source samples preserved. Spoken word identity remains unverified.' if preserve_samples else 'Acoustic cuts/mono PCM/energy checks PASS. Word identity, omissions, order and spoken repeats REQUIRE listening.'))}
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

def _verified_no_audio_state(attempt,work,master):
    """Recognize only a complete, persisted response known to contain no audio.

    The legacy branch is deliberately narrow for the current marker format:
    one parsed response, finishReason OTHER, and no persisted payload/output.
    New markers carry the explicit audio_part_count/audio_payload_received facts.
    """
    attempt=Path(attempt);work=Path(work);master=Path(master);metadata_path=work/'response_metadata.json'
    if (not attempt.is_file() or attempt.is_symlink() or not metadata_path.is_file() or
            metadata_path.is_symlink() or (work/'response_audio.bin').exists() or
            master.exists() or master.with_suffix('.tmp.wav').exists()):
        return None
    try:
        state=json.loads(attempt.read_text(encoding='utf-8'))
        metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
        if not isinstance(state,dict) or not isinstance(metadata,dict):return None
        if state.get('model')!=MODEL or state.get('voice')!=VOICE:return None
        attempts=state.get('attempts')
        if not isinstance(attempts,list) or not attempts:return None
        last=attempts[-1]
        if not isinstance(last,dict) or state.get('automatic_retry') is not False:return None
        marker_status=state.get('status');last_status=last.get('status')
        if 'audio_part_count' in metadata or 'audio_payload_received' in metadata:
            count=metadata.get('audio_part_count')
            if (isinstance(count,bool) or count!=0 or metadata.get('audio_payload_received') is not False or
                    last_status not in ('response_received','response_received_no_audio') or
                    marker_status not in ('attempted_once','response_received','response_received_no_audio')):
                return None
            return state
        # Compatibility for markers created before audio-part metadata existed.
        if (marker_status=='attempted_once' and last_status=='response_received' and len(attempts)==1 and
                metadata.get('finish_reasons')==['OTHER']):
            return state
    except Exception:
        return None
    return None

def _prepare_verified_no_audio_retry(attempt,work,master):
    state=_verified_no_audio_state(attempt,work,master)
    if state is None:
        raise Stop('Existing request marker is not a verified no-audio response. Unknown outcomes and responses with any audio payload stay blocked; do not delete the marker.')
    metadata_path=Path(work)/'response_metadata.json'
    try:
        retries=state.get('manual_no_audio_retries',0)
        if isinstance(retries,bool) or not isinstance(retries,int) or retries<0:
            raise ValueError('invalid manual retry count')
        history_root=Path(work)/'no_audio_attempt_history'
        if history_root.is_symlink():raise ValueError('history path is a symlink')
        history_root.mkdir(exist_ok=True)
        history=history_root/('recovery-%04d-%s'%(retries+1,time.time_ns()))
        history.mkdir()
        shutil.copy2(attempt,history/'request_attempt.json')
        shutil.copy2(metadata_path,history/'response_metadata.json')
        armed={'model':state.get('model',MODEL),'voice':state.get('voice',VOICE),
               'status':'manual_no_audio_retry_armed','automatic_retry':False,
               'manual_no_audio_retries':retries+1,
               'last_manual_recovery':{'type':'verified_no_audio','history':history.name},
               'attempts':[]}
        _write_json_atomic(attempt,armed)
        # Prevent stale metadata from proving the outcome of this new request
        # if execution stops before the response is recorded.
        metadata_path.unlink()
        return armed
    except Stop:
        raise
    except Exception as e:
        raise Stop('Could not safely archive the verified no-audio response; no retry was sent (%s).'%type(e).__name__) from None

def generate(story,texts,master,work,key_file,backup_key=None,retry_verified_no_audio=False):
    # Exact same numeric facts, spoken words before any key/request.
    from km_ctc import spoken_form,AlignmentStop
    converted=[]
    for text in texts:
        try:converted.append(spoken_form(text)[0])
        except Exception as e:
            print('NOTE: spoken-form helper could not verify one text span (%s); sending the approved text unchanged.'%type(e).__name__,flush=True)
            converted.append(text)
    texts=converted
    # Durable attempt marker BEFORE key/network. Unknown outcomes never retry.
    attempt=work/'request_attempt.json'
    candidates=list(dict.fromkeys((key_file,backup_key or key_file.with_name('gemini_key2.txt'))))
    preloaded_keys={}
    if attempt.exists():
        if not retry_verified_no_audio:
            if _verified_no_audio_state(attempt,work,master) is not None:
                raise Stop('Gemini returned a response with no audio and no output bytes were saved. Run py resume_failed.py <REVIEW_ID> for one explicit recovery request; unknown outcomes remain blocked.')
            raise Stop('An earlier request marker blocks this audio. Unknown outcomes and responses with audio stay blocked; do not delete the marker manually.')
        if _verified_no_audio_state(attempt,work,master) is None:
            raise Stop('Existing request marker is not a verified no-audio response. Unknown outcomes and responses with any audio payload stay blocked; do not delete the marker.')
        if not key_file.is_file():raise Stop('Key file 1 missing. No request sent; verified no-audio marker retained.')
        preloaded_keys[key_file]=key_file.read_text(encoding='utf-8').strip()
        if not preloaded_keys[key_file]:raise Stop('Key file 1 empty. No request sent; verified no-audio marker retained.')
        state=_prepare_verified_no_audio_retry(attempt,work,master)
    else:
        state={'model':MODEL,'voice':VOICE,'status':'attempted_once','automatic_retry':False,'manual_no_audio_retries':0,'attempts':[]}

    tone_tags=[]
    for index,card in enumerate(story['cards'],1):
        tag=str(card.get('voice_tone','neutral')).strip()
        if tag not in TONE_MAP:
            print('NOTE: card %s has an unknown voice_tone; using the existing neutral delivery direction.'%index,flush=True)
            tag='neutral'
        tone_tags.append(tag)
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
    answer=None
    for index,candidate in enumerate(candidates,1):
        slot=2 if candidate.name=='gemini_key2.txt' else 1
        print('Voice request using key file slot %s (%s).'%(slot,candidate.name),flush=True)
        if not candidate.is_file():
            raise Stop('Key file %s missing. No request sent on this key; existing attempt marker retained if a request already happened.'%index)
        key=preloaded_keys.pop(candidate,None)
        if key is None:key=candidate.read_text(encoding='utf-8').strip()
        if not key:raise Stop('Key file %s empty; nothing sent on this key.'%index)
        state['attempts'].append({'key_slot':slot,'key_file':candidate.name,'status':'attempted'})
        state['status']='attempted_once'
        _write_json_atomic(attempt,state)
        req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+MODEL+':generateContent',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=300) as r:answer=json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:body=e.read(65536).decode('utf-8',errors='replace')
            except Exception:body=''
            reason=definite_key_rejection(e.code,body)
            state['attempts'][-1].update(status='http_rejected' if reason else 'http_failure_no_safe_failover',http_status=e.code,failover_reason=reason)
            _write_json_atomic(attempt,state)
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
            state['status']='unknown_outcome'
            _write_json_atomic(attempt,state)
            raise Stop('Request failed/timeout on key slot %s. Quota outcome unknown; no fallback or retry. Attempt marker kept.'%slot) from None
        finally:key=None
        print('Voice response received using key slot %s (%s).'%(slot,candidate.name),flush=True)
        state['attempts'][-1]['status']='response_received'
        state['status']='response_received'
        _write_json_atomic(attempt,state)
        break
    candidates=answer.get('candidates',[]) if isinstance(answer,dict) else []
    if not isinstance(candidates,list):candidates=[]
    parts=[]
    for candidate_data in candidates:
        content=candidate_data.get('content',{}) if isinstance(candidate_data,dict) else {}
        candidate_parts=content.get('parts',[]) if isinstance(content,dict) else []
        if isinstance(candidate_parts,list):parts.extend(candidate_parts)
    audio=[]
    for part in parts:
        inline=part.get('inlineData',{}) if isinstance(part,dict) else {}
        if isinstance(inline,dict) and isinstance(inline.get('data'),str) and inline['data']:
            audio.append(inline)
    metadata={'finish_reasons':[c.get('finishReason') for c in candidates if isinstance(c,dict)],
              'usage':answer.get('usageMetadata',{}) if isinstance(answer,dict) else {},
              'response_model':answer.get('modelVersion') if isinstance(answer,dict) else None,
              'audio_part_count':len(audio),'audio_payload_received':bool(audio)}
    _write_json_atomic(work/'response_metadata.json',metadata)
    if not audio:
        state['attempts'][-1]['status']='response_received_no_audio'
        state['attempts'][-1]['audio_part_count']=0
        state['status']='response_received_no_audio'
        _write_json_atomic(attempt,state)
        raise Stop('Gemini returned no audio. No output bytes were saved. Run py resume_failed.py <REVIEW_ID> to retry this verified no-audio result; unknown outcomes remain blocked.')
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
    _write_json_atomic(attempt,state)

def build_two_halves(story,texts,master,work,project,asr_model=None,cuts=None,recover_missing=False,offline=False,retry_verified_no_audio=False):
    """Retain original halves; missing cards have independent durable requests."""
    from km_ctc import Engine,AlignmentStop,digest
    engine=None;preflight_note=''
    if cuts is None:
        try:
            engine=Engine(project/'models'/'km_nepali_ctc')
            engine.check_texts(texts);engine.load()
        except Exception as e:
            # CTC is a quality check, not a gate on an approved reel. If the
            # pinned local model is unavailable, use retained Gemini audio and
            # split it softly after generation instead of stranding the story.
            preflight_note=type(e).__name__+': '+str(e)
            engine=None
            print('NOTE: CTC preflight unavailable; approved audio will use a soft split: '+preflight_note[:240],flush=True)
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
            generate({'cards':story['cards'][lo:hi]},texts[lo:hi],audio,folder,primary,backup,retry_verified_no_audio)
        metadata_file=folder/'response_metadata.json'
        try:
            metadata=json.loads(metadata_file.read_text(encoding='utf-8')) if metadata_file.is_file() else {}
            reasons=metadata.get('finish_reasons',[]) if isinstance(metadata,dict) else []
        except Exception as e:
            reasons=[]
            print('NOTE: half %s response metadata could not be read (%s); retained audio will be analyzed independently.'%(number,type(e).__name__),flush=True)
        if not reasons or any(r!='STOP' for r in reasons):
            print('NOTE: half %s returned valid audio with finishReason %s; keeping the audio and using soft alignment if needed.'%(number,','.join(str(x) for x in reasons)[:120]),flush=True)
    # Analyze every original half before spending on any recovery: a later failed
    # boundary must not be discovered after earlier recovery already used quota.
    fits=[]
    for number,(lo,hi) in enumerate(ranges,1):
        folder=work/('half%s'%number);audio=folder/'master.wav';rate,values=read_wav(audio)
        if cuts is None and engine is None:
            from km_ctc import best_effort_alignment
            fit=best_effort_alignment(audio,texts[lo:hi],folder/'ctc',preflight_note or 'CTC model unavailable')
            print('NOTE: Half %s uses the audio-only soft split.'%number,flush=True)
            fits.append(fit)
        elif cuts is None:
            try:
                fit=engine.analyze(audio,texts[lo:hi],folder/'ctc')
                if not _valid_fit(fit,hi-lo):raise AlignmentStop('CTC returned an incomplete alignment plan')
            except Exception as e:
                from km_ctc import best_effort_alignment
                fit=best_effort_alignment(audio,texts[lo:hi],folder/'ctc',str(e))
                print('NOTE: Half %s CTC check used a soft audio split: %s'%(number,str(e)[:240]),flush=True)
            fits.append(fit)
        else:fits.append(None)
    for number,((lo,hi),fit) in enumerate(zip(ranges,fits),1):
        folder=work/('half%s'%number);audio=folder/'master.wav';rate,values=read_wav(audio)
        primary=project/('gemini_key.txt' if number==1 else 'gemini_key2.txt');backup=project/('gemini_key2.txt' if number==1 else 'gemini_key.txt')
        use_audio=audio;use_cuts=None;repair_rows=[];sync_method='unknown'
        if fit is not None:
            if fit.get('best_effort') or fit.get('partial_missing_indices'):
                use_audio,use_cuts,repair_rows=_isolate_uncertain_half(
                    story,texts,lo,hi,folder,rate,project,primary,backup,
                    offline=offline,retry_verified_no_audio=retry_verified_no_audio)
                sync_method='isolated_per_card' if len(repair_rows)==hi-lo else 'uncertain_soft_split'
            elif fit['missing_indices']:
                if not recover_missing or offline:
                    # The normal approved-reel command must not leave a known
                    # missing line attached to a duration-estimated clip. The
                    # offline install pass reuses these exact clips when cached.
                    use_audio,use_cuts,repair_rows=_isolate_uncertain_half(
                        story,texts,lo,hi,folder,rate,project,primary,backup,
                        offline=offline,retry_verified_no_audio=retry_verified_no_audio)
                    sync_method='isolated_per_card' if len(repair_rows)==hi-lo else 'uncertain_soft_split'
                else:
                    print('MISSING ONLY:',', '.join(str(lo+i+1) for i in fit['missing_indices']))
                    present=fit['present_indices']
                    split_audio(audio,[texts[lo+i] for i in present],folder/'present_cards',fit['cuts_sec'],preserve_samples=True)
                    card_paths={idx:folder/'present_cards'/('c%02d.wav'%(i+1)) for i,idx in enumerate(present)}
                    for idx in fit['missing_indices']:
                        global_idx=lo+idx
                        recovery=folder/'missing_cards'/('c%02d'% (global_idx+1));recovery.mkdir(parents=True,exist_ok=True)
                        recovered=recovery/'master.wav'
                        if not recovered.exists():
                            print('Requesting ONLY missing card %s; original halves kept.'%(global_idx+1))
                            generate({'cards':[story['cards'][global_idx]]},[texts[global_idx]],recovered,recovery,primary,backup,retry_verified_no_audio)
                        split_audio(recovered,[texts[global_idx]],recovery/'cards',[],preserve_samples=True)
                        card_paths[idx]=recovery/'cards'/'c01.wav'
                        repair_rows.append({'card':global_idx+1,'master_sha256':digest(recovered)})
                    # Restore original STORY order; exact cuts are centered in
                    # two seconds of silence inserted between separate clips.
                    rebuilt=[];local=[]
                    for i in range(hi-lo):
                        r,v=read_wav(card_paths[i])
                        if r!=rate:
                            print('NOTE: recovered card sample rate differs; resampling it to match the retained half.',flush=True)
                            v=_resample_pcm16(v,r,rate)
                        if i:local.append((len(rebuilt)+rate)/rate);rebuilt.extend([0]*(rate*2))
                        rebuilt.extend(v)
                    use_audio=folder/'repaired_master.wav';temp=folder/'repaired_master.tmp.wav';write_wav(temp,rate,rebuilt);temp.replace(use_audio);use_cuts=local
                    _write_json_atomic(folder/'recovery_receipt.json',{'original_sha256':digest(audio),'missing_cards':repair_rows,'repaired_sha256':digest(use_audio),'cuts_sec':local})
                    sync_method='ctc_missing_recovered'
            else:
                use_cuts=fit['cuts_sec'];sync_method='ctc_boundaries'
        else:
            use_cuts=[v-offset for v in cuts[lo:hi-1]];sync_method='manual_cuts'
        soft=bool(fit and fit.get('best_effort'))
        preserve=sync_method in ('ctc_boundaries','ctc_missing_recovered','isolated_per_card','manual_cuts')
        result=split_audio(use_audio,texts[lo:hi],folder/'cards',use_cuts,soft_fallback=soft,fallback_note=fit.get('fallback_reason','') if fit else '',preserve_samples=preserve)
        if asr_model:
            # Independent optional validator. It may annotate the reel, never gate it.
            try:
                words=local_asr_words(use_audio,folder,asr_model)
                from km_ctc import similarity
                heard=' '.join(w['word'] for w in words)
                ratio=similarity(' '.join(texts[lo:hi]),heard)
                expected=[norm_token(w) for t in texts[lo:hi] for w in t.split() if norm_token(w)]
                got=[norm_token(w['word']) for w in words if norm_token(w['word'])]
                unexpected=[got[i] for i in range(1,len(got)) if got[i]==got[i-1] and not any(expected[k]==expected[k-1]==got[i] for k in range(1,len(expected)))]
                if ratio<.85:print('NOTE: optional Whisper comparison is uncertain (%.1f%%); retained approved audio is unchanged.'%(ratio*100),flush=True)
                if unexpected:print('NOTE: optional Whisper found possible repeated words; retained approved audio is unchanged.',flush=True)
            except Exception as e:
                print('NOTE: optional Whisper check unavailable (%s); retained approved audio is unchanged.'%type(e).__name__,flush=True)
        rate,values=read_wav(use_audio);seconds=len(values)/rate
        diagnostics.append({'half':number,'card_count':hi-lo,'sync_method':sync_method,'original_master_sha256':digest(audio),'used_master_sha256':digest(use_audio),'seconds':seconds,'ctc':fit,'recovered':repair_rows,'manual_override':cuts is not None,'word_identity_certified':False})
        all_cuts.extend(offset+c for c in result['cuts_sec']);pieces.append((rate,values));offset+=seconds
        if number<len(ranges):all_cuts.append(offset+1);offset+=2
    rate=pieces[0][0];joined=[]
    for i,(piece_rate,values) in enumerate(pieces):
        if piece_rate!=rate:
            print('NOTE: half sample rate differs; resampling it to match the first half.',flush=True)
            values=_resample_pcm16(values,piece_rate,rate)
        if i:joined.extend([0]*(rate*2))
        joined.extend(values)
    tmp=work/'two_halves_joined.tmp.wav';write_wav(tmp,rate,joined)
    if master.exists() and digest(master)!=digest(tmp):
        old=work/('retained_joined_'+digest(master)[:16]+'.wav')
        if not old.exists():shutil.copy2(master,old)
    tmp.replace(master)
    _write_json_atomic(work/'two_half_join.json',{'design':'line_sync_v2','half_ranges':ranges,'cuts_sec':all_cuts,'diagnostics':diagnostics,'master_sha256':digest(master),'internal_word_completeness':'CTC provisional; line-to-audio mapping is recorded separately from word identity.'})
    return all_cuts

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('story');ap.add_argument('--audio',help='Offline master WAV; never reads key or calls Gemini');ap.add_argument('--cuts');ap.add_argument('--asr-model',help='Optional already-installed faster-whisper model directory, CPU offline only');ap.add_argument('--install-reviewed',action='store_true');ap.add_argument('--recover-missing',action='store_true',help='Recover only confidently absent cards, never unknown outcomes');ap.add_argument('--retry-verified-no-audio',action='store_true',help='Permit one explicit request for a prior response proven to contain no audio; unknown outcomes remain blocked');args=ap.parse_args()
    project=Path(__file__).resolve().parent.parent;story=json.loads(Path(args.story).read_text(encoding='utf-8'));texts=[str(c.get('vo','')).strip() for c in story.get('cards',[])]
    if not texts or any(not t for t in texts):raise Stop('Every card must have nonempty vo.')
    tags=[]
    for i,card in enumerate(story['cards'],1):
        tag=str(card.get('voice_tone','neutral')).strip()
        if tag not in TONE_MAP:
            print('NOTE: card %s has an unknown voice_tone; neutral delivery will be used without changing the story.'%i,flush=True)
            tag='neutral'
        tags.append(tag)
    print('DELIVERY PER CARD:', ', '.join(str(i+1)+' '+tag for i,tag in enumerate(tags)))
    fingerprint=hashlib.sha256(json.dumps([texts,[c.get('voice_tone','neutral') for c in story['cards']],MODEL,VOICE,'two_halves_v1'],ensure_ascii=False).encode()).hexdigest()[:20]
    work=project/'one_call_voice'/fingerprint;work.mkdir(parents=True,exist_ok=True)
    from km_ctc import spoken_form,SP_NUMBER_REVISION
    numeric_targets=[]
    for t in texts:
        try:
            spoken,mapping=spoken_form(t)
            numeric_targets.append({'original':t,'spoken':spoken,'mapping':mapping})
        except Exception as e:
            numeric_targets.append({'original':t,'spoken':t,'mapping':[],'note':'spoken-form helper unavailable: '+type(e).__name__})
    (work/'spoken_number_targets.json').write_text(json.dumps({'version':SP_NUMBER_REVISION,'targets':numeric_targets},ensure_ascii=False,indent=2),encoding='utf-8')
    for i,row in enumerate(numeric_targets,1):
        for item in row['mapping']:
            if item.get('note'):print('SPOKEN TARGET NOTE card %s: %s -> %s. %s'%(i,item['original'],item['spoken'],item['note']))
    master=work/'master.wav';dest=work/'cards'
    receipt=work/'installed_reviewed.json';public=project/'public/voice_in'
    if receipt.exists() and not args.audio and not args.cuts and not args.install_reviewed:
        try:
            records=json.loads(receipt.read_text(encoding='utf-8'))
            expected={'c%02d.wav'%(i+1) for i in range(len(texts))}
            names=[item.get('name') for item in records if isinstance(item,dict)] if isinstance(records,list) else []
            valid=(isinstance(records,list) and len(records)==len(texts) and len(names)==len(texts) and
                   set(names)==expected and
                   all(isinstance(item.get('sha256'),str) and (public/item['name']).is_file() and
                       hashlib.sha256((public/item['name']).read_bytes()).hexdigest()==item['sha256']
                       for item in records if isinstance(item,dict)))
        except Exception:
            valid=False
        if valid:
            reusable,reason=cached_voice_sync_status(work,len(texts))
            if reusable:
                print('Reviewed voices already installed for this exact script/tones with a verified line-to-audio plan. ZERO Gemini calls. Ready to render.')
                return
            valid=False
            print('NOTE: saved voice receipt is not reused (%s); rebuilding card timing from retained source audio when available.'%reason,flush=True)
        else:
            print('NOTE: reviewed voice receipt or installed-file check is uncertain; rebuilding from retained audio when available.',flush=True)
    if args.audio:
        src=Path(args.audio).resolve();read_wav(src)
        if master.exists() and master.read_bytes()!=src.read_bytes():raise Stop('Different offline master already cached. Use a separate test directory; refusing overwrite.')
        if src!=master.resolve():shutil.copy2(src,master)
    cuts=json.loads(Path(args.cuts).read_text()) if args.cuts else None
    if not args.audio and cuts is not None and master.exists():
        print('Reviewed manual cuts on retained joined master. ZERO requests; CTC semantic gates bypassed.')
    elif not args.audio:
        cuts=build_two_halves(story,texts,master,work,project,args.asr_model,cuts,args.recover_missing,offline=args.install_reviewed,retry_verified_no_audio=args.retry_verified_no_audio)
    elif cuts is None:
        from km_ctc import Engine,AlignmentStop
        try:
            fit=Engine(project/'models'/'km_nepali_ctc').analyze(master,texts,work/'offline_ctc')
        except AlignmentStop as e:raise Stop(str(e)) from None
        if fit['missing_indices']:raise Stop('Offline audio has missing cards. No keys read or recovery requests in --audio mode.')
        cuts=fit['cuts_sec']
    # Explicit fixture analysis stays strict; the approved build path always
    # converts uncertain cut checks to a note and sample-preserving fallback.
    preserve=False
    if not args.audio and cuts is not None:
        preserve,_=cached_voice_sync_status(work,len(texts))
    report=split_audio(master,texts,dest,cuts,args.asr_model,auto_soft=not bool(args.audio),preserve_samples=preserve,
                       fallback_note='Cuts map to line-specific audio clips or validated CTC boundaries; preserving their samples.' if preserve else '')
    print('MASTER KEPT:',master);print('STAGED CARDS:',dest)
    for row in report['cards']:print('card %02d: %.2fs | text/repeats NOT VERIFIED'%(row['card'],row['duration_sec']))
    if report.get('soft_fallback'):
        print('NOTE: soft audio split used. Card word identity, omissions, order and exact boundaries are unverified; source samples were retained.')
    elif report.get('sample_preserving'):
        print('NOTE: line-to-audio cuts were preserved from the durable sync plan. Spoken word identity remains unverified.')
    else:
        print('Acoustic split checks passed. Completeness thresholds are provisional; listen to every staged card for words/repeats before installation. No caption word alignment produced.')
    if args.install_reviewed:
        public=project/'public/voice_in';public.mkdir(parents=True,exist_ok=True)
        backup=work/'previous_voice_in'
        if backup.exists():backup=work/('previous_voice_in_'+str(time.time_ns()))
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
