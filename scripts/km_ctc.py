"""Offline conservative Nepali card alignment. No keys or remote inference."""
import difflib,hashlib,itertools,json,math,os,re,unicodedata,wave
from pathlib import Path
VERSION='km-onnx-int8-1'
REPO='gagan3012/wav2vec2-xlsr-nepali'
REVISION='d1dc1c34a3f2387d00d4bfe351e940cb7c06fb80'
class AlignmentStop(RuntimeError):pass

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

NUMBER_NAMES={0: 'सुन्ना', 1: 'एक', 2: 'दुई', 3: 'तीन', 4: 'चार', 5: 'पाँच', 6: 'छ', 7: 'सात', 8: 'आठ', 9: 'नौ', 10: 'दस', 11: 'एघार', 12: 'बाह्र', 13: 'तेह्र', 14: 'चौध', 15: 'पन्ध्र', 16: 'सोह्र', 17: 'सत्र', 18: 'अठार', 19: 'उन्नाइस', 20: 'बिस', 21: 'एक्काइस', 22: 'बाइस', 23: 'तेइस', 24: 'चौबिस', 25: 'पच्चिस', 26: 'छब्बिस', 27: 'सत्ताइस', 28: 'अट्ठाइस', 29: 'उनन्तिस', 30: 'तिस', 31: 'एकतिस', 32: 'बत्तिस', 33: 'तेत्तिस', 34: 'चौतिस', 35: 'पैँतिस', 36: 'छत्तिस', 37: 'सैँतिस', 38: 'अठतिस', 39: 'उनन्चालिस', 40: 'चालिस', 41: 'एकचालिस', 42: 'बयालिस', 43: 'त्रिचालिस', 44: 'चवालिस', 45: 'पैँतालिस', 46: 'छयालिस', 47: 'सतचालिस', 48: 'अठचालिस', 49: 'उनन्चास', 50: 'पचास', 51: 'एकाउन्न', 52: 'बाउन्न', 53: 'त्रिपन्न', 54: 'चवन्न', 55: 'पचपन्न', 56: 'छपन्न', 57: 'सन्ताउन्न', 58: 'अन्ठाउन्न', 59: 'उनसट्ठी', 60: 'साठी', 61: 'एकसट्ठी', 62: 'बयसट्ठी', 63: 'त्रिसट्ठी', 64: 'चौसट्ठी', 65: 'पैँसट्ठी', 66: 'छयसट्ठी', 67: 'सतसट्ठी', 68: 'अठसट्ठी', 69: 'उनन्सत्तरी', 70: 'सत्तरी', 71: 'एकहत्तर', 72: 'बहत्तर', 73: 'त्रिहत्तर', 74: 'चौहत्तर', 75: 'पचहत्तर', 76: 'छयहत्तर', 77: 'सतहत्तर', 78: 'अठहत्तर', 79: 'उनासी', 80: 'असी', 81: 'एकासी', 82: 'बयासी', 83: 'त्रियासी', 84: 'चौरासी', 85: 'पचासी', 86: 'छयासी', 87: 'सतासी', 88: 'अठासी', 89: 'उनान्नब्बे', 90: 'नब्बे', 91: 'एकान्नब्बे', 92: 'बयान्नब्बे', 93: 'त्रियान्नब्बे', 94: 'चौरान्नब्बे', 95: 'पन्चान्नब्बे', 96: 'छयान्नब्बे', 97: 'सन्तान्नब्बे', 98: 'अन्ठान्नब्बे', 99: 'उनान्सय'}
# Cardinal spellings: https://omniglot.com/language/numbers/nepali.htm
# Decimal/grouping rules: https://nepalilanguage.org/numbers/
SP_NUMBER_REVISION='numbers-english-unverified-v4'

def nepali_integer(n):
    if not 0<=n<10**14:raise AlignmentStop('Number outside supported exact spoken range; no request made.')
    if n<100:return NUMBER_NAMES[n]
    for value,name in ((10**11,'खर्ब'),(10**9,'अर्ब'),(10**7,'करोड'),(10**5,'लाख'),(1000,'हजार'),(100,'सय')):
        if n>=value:
            q,r=divmod(n,value)
            return nepali_integer(q)+' '+name+(' '+nepali_integer(r) if r else '')

def spoken_form(text):
    """Numeric voice target, preserving source display/cache and logging fallback notes."""
    mapping=[];lat=str.maketrans('०१२३४५६७८९','0123456789')
    # One complete digit/punctuation span. Ambiguous forms are read literally,
    # never guessed into an amount, date, range or sporting result.
    pattern=r'[+−-]?[0-9०-९]+(?:[,.:/\-–—][0-9०-९]+)*'
    separators={',':'अल्पविराम','.':'दशमलव',':':'कोलन','/':'स्ल्यास','-':'ड्यास','–':'ड्यास','—':'ड्यास','−':'ऋण','+':'जोड'}
    def literal(raw):
        return ' '.join(NUMBER_NAMES[int(ch.translate(lat))] if ch in '0123456789०१२३४५६७८९' else separators.get(ch,'') for ch in raw).strip()
    def apply(m):
        raw=m.group();number=raw.translate(lat);after=text[m.end():];before=text[:m.start()];note=''
        simple=re.fullmatch(r'[+−-]?[0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?',number)
        sign=''
        core=number
        if core[:1] in ('+','−','-'):sign={'-':'ऋण ','−':'ऋण ','+':'जोड '}[core[0]];core=core[1:]
        whole,sep,frac=core.partition('.')
        groups=whole.split(',');grouped=len(groups)==1 or (1<=len(groups[0])<=3 and len(groups[-1])==3 and (all(len(x)==2 for x in groups[1:-1]) or all(len(x)==3 for x in groups[1:])))
        digits=whole.replace(',','')
        embedded=bool(before and before[-1].isalnum()) or after.startswith(('औ','ौँ','ौं'))
        if simple and grouped and not embedded and not (len(digits)>1 and digits.startswith('0')) and len(digits)<=14 and int(digits)<10**14:
            spoken=sign+nepali_integer(int(digits))
            if sep:spoken+=' दशमलव '+' '.join(NUMBER_NAMES[int(c)] for c in frac)
        else:
            spoken=literal(raw);note='Ambiguous/identifier numeric span read literally by digits and separators; source meaning not inferred.'
        mapping.append({'original':raw,'spoken':spoken,'start':m.start(),'end':m.end(),'rule':SP_NUMBER_REVISION,'note':note})
        return (' ' if before and before[-1].isalnum() else '')+spoken+(' ' if after and after[0].isalpha() else '')
    out=re.sub(pattern,apply,text).replace('%',' प्रतिशत')
    for m in re.finditer(r'[A-Za-zÀ-ÖØ-öø-ÿ]+',out):
        mapping.append({'original':m.group(),'spoken':m.group(),'start':m.start(),'end':m.end(),'stage':'after_numeric_expansion','rule':SP_NUMBER_REVISION,'note':'English preserved for voice; Latin span unverified by Nepali-only CTC.'})
    return out,mapping

def normalize(text,vocab):
    # Numeric/Latin targets are expanded deterministically, never silently omitted.
    text=unicodedata.normalize('NFC',spoken_form(text)[0])
    has_latin=bool(re.search(r'[A-Za-zÀ-ÖØ-öø-ÿ]',text))
    text=re.sub(r'[A-Za-zÀ-ÖØ-öø-ÿ]+',' ',text)  # Explicitly unverified Latin, not a pronunciation claim.
    if any(ch.isdigit() for ch in text):raise AlignmentStop('Unsupported digit script after expansion; local target error, no request made.')
    keep=[]
    for ch in text:
        if ch.isspace():keep.append(' ')
        elif unicodedata.category(ch)[0] in ('P','S'):continue
        elif ch in vocab:keep.append(ch)
        else:raise AlignmentStop('Unsupported narration character U+%04X. Use exact spoken-form Nepali text or reviewed --cuts.'%ord(ch))
    out=re.sub(r'\s+',' ',''.join(keep)).strip().replace(' ','|')
    if not out:
        if has_latin:return ''
        raise AlignmentStop('Empty normalized narration.')
    return out

def letters(s):return ''.join(ch for ch in unicodedata.normalize('NFC',s) if unicodedata.category(ch)[0] in ('L','M'))
def similarity(a,b):return difflib.SequenceMatcher(None,letters(a),letters(b),autojunk=False).ratio()

class Engine:
    def __init__(self,model_dir):
        self.path=Path(model_dir).resolve()
        manifest=self.path/'km_model_manifest.json'
        if not manifest.is_file():raise AlignmentStop('Pinned CTC model missing. Run the installer once with --setup-model; no Gemini request made.')
        info=json.loads(manifest.read_text(encoding='utf-8'))
        if info.get('repo')!=REPO or info.get('revision')!=REVISION:raise AlignmentStop('CTC model pin mismatch. No request made.')
        for name,expected in info['files'].items():
            p=self.path/name
            if not p.is_file() or digest(p)!=expected:raise AlignmentStop('CTC model damaged: '+name+'. Rerun --setup-model, no Gemini request made.')
        self.vocab=json.loads((self.path/'vocab.json').read_text(encoding='utf-8'));self.chars=[None]*len(self.vocab)
        for ch,i in self.vocab.items():self.chars[i]=ch
        if self.vocab.get('[PAD]')!=64:raise AlignmentStop('Unexpected CTC blank ID; expected 64.')
    def check_texts(self,texts):
        targets=[]
        for i,text in enumerate(texts,1):
            try:targets.append(normalize(text,self.vocab))
            except AlignmentStop as e:raise AlignmentStop('Narration preflight card %s: %s'%(i,e)) from None
        return targets
    def load(self):
        # Preflight before ANY Gemini request, no heavyweight model load here.
        try:
            import numpy,onnxruntime,km_segmentation
        except ImportError as e:raise AlignmentStop('Minimal local dependencies missing. Run the lightweight installer --setup-model. '+str(e)) from None
        import shutil
        if not shutil.which('ffmpeg'):raise AlignmentStop('ffmpeg not on PATH. Fix the existing renderer ffmpeg setup before any voice request.')
    def infer(self,master,cache):
        import numpy as np
        cache=Path(cache);cache.mkdir(parents=True,exist_ok=True);h=digest(master)
        with wave.open(str(master),'rb') as w:
            if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getcomptype()!='NONE':raise AlignmentStop('CTC needs mono PCM16 WAV.')
            rate=w.getframerate();a=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
        duration=len(a)/rate
        if duration>90:raise AlignmentStop('Half over 90 seconds: memory-safe automatic inference not supported; use reviewed --cuts.')
        meta=cache/'ctc_inference.json';arr=cache/'ctc_logp.npy'
        ident={'master_sha256':h,'model_revision':REVISION,'engine':VERSION}
        if meta.is_file() and arr.is_file():
            old=json.loads(meta.read_text(encoding='utf-8'))
            if all(old.get(k)==v for k,v in ident.items()) and old.get('logp_sha256')==digest(arr):
                lp=np.load(arr,allow_pickle=False)
                if lp.ndim==2 and lp.shape[1]==65 and np.isfinite(lp).all():return a,rate,lp,old['greedy']
        self.load()
        import subprocess,sys
        temp=cache/'ctc_logp.tmp.npy';greedy_file=cache/'ctc_greedy.tmp.json'
        worker=Path(__file__).with_name('km_onnx_worker.py')
        result=subprocess.run([sys.executable,str(worker),str(self.path),str(master),str(temp),str(greedy_file)])
        if result.returncode!=0:raise AlignmentStop('Local ONNX inference failed. Original audio retained; no automatic Gemini retry.')
        lp=np.load(temp,allow_pickle=False)
        if lp.ndim!=2 or lp.shape[1]!=65 or not np.isfinite(lp).all():raise AlignmentStop('Invalid cached ONNX logits; refusing cuts.')
        greedy=json.loads(greedy_file.read_text(encoding='utf-8'))['greedy'];temp.replace(arr);greedy_file.unlink()
        meta.write_text(json.dumps({**ident,'greedy':greedy,'duration':duration,'logp_sha256':digest(arr)},ensure_ascii=False,indent=2),encoding='utf-8')
        return a,rate,lp,greedy
    def align(self,lp,duration,texts):
        from km_segmentation import CtcSegmentationParameters,prepare_text,ctc_segmentation,determine_utterance_segments
        cfg=CtcSegmentationParameters(char_list=self.chars);cfg.blank=64;cfg.index_duration=duration/len(lp);cfg.replace_spaces_with_blanks=False
        gt,idx=prepare_text(cfg,texts);tim,prob,_=ctc_segmentation(cfg,lp,gt)
        seg=determine_utterance_segments(cfg,idx,prob,tim,texts)
        brackets=[]
        for k in idx[1:-1]:
            brackets.append((float(tim[k-1]),float(tim[k+1])))
        return seg,brackets
    def subset(self,lp,duration,texts,greedy):
        # All subsets in order; absence is distinct from an uncertain full alignment.
        # Unknown/extra speech must not be interpreted as a missing card.
        if len(texts)>6:raise AlignmentStop('More than six cards in one half unsupported; use reviewed --cuts.')
        choices=[]
        for bits in itertools.product((False,True),repeat=len(texts)):
            selected=[i for i,b in enumerate(bits) if b]
            if not selected:continue
            wanted=[texts[i] for i in selected]
            ratio=similarity(' '.join(wanted),greedy)
            if ratio<.72:continue
            try:seg,brackets=self.align(lp,duration,wanted)
            except Exception:continue
            if min(s[2] for s in seg)<-2.2:continue
            # Penalize dropping text unless the audio strongly selects this subset.
            quality=ratio + .035*len(selected)
            choices.append({'selected':selected,'ratio':ratio,'segments':seg,'brackets':brackets,'quality':quality})
        if not choices:raise AlignmentStop('No confident card set: possible omissions, repeats or wrong words. Originals kept; no missing-card request authorized.')
        choices.sort(key=lambda x:x['quality'],reverse=True);best=choices[0]
        if len(choices)>1 and best['quality']-choices[1]['quality']<.08:
            raise AlignmentStop('Ambiguous card set: multiple text subsets fit. Originals kept; no guessed cut or recovery request.')
        missing=[i for i in range(len(texts)) if i not in best['selected']]
        if missing:
            # A weak score alone is insufficient proof of absence. Require the
            # omitted text to have little match anywhere in the greedy transcript.
            heard=letters(greedy)
            for i in missing:
                target=letters(texts[i]);width=max(1,len(target));matches=[]
                for start in range(0,len(heard),max(1,width//8)):
                    matches.append(similarity(target,heard[start:start+width]))
                if matches and max(matches)>.55:raise AlignmentStop('Possible partial missing card %s: words may overlap existing audio. Stop, review; no recovery request.'%(i+1))
        return {**best,'missing':missing,'alternatives':len(choices)}
    def joint_cuts(self,a,rate,brackets,segments):
        import numpy as np
        rows=[];duration=len(a)/rate
        for i,(left,right) in enumerate(brackets):
            # Character posteriors peak inside phonemes, not at their edges.
            # Margin and >=120ms valley prevent cutting directly at token peaks.
            lo=left+.10;hi=right-.10;choices=[]
            if hi<=lo:raise AlignmentStop('Boundary %s: no safe character bracket.'%(i+1))
            hop=max(1,int(rate*.01));rms=[];ts=[]
            for j in range(int(lo*rate),int(hi*rate)-hop,hop):
                rms.append(float(np.sqrt(np.mean(a[j:j+hop]**2))));ts.append((j+hop/2)/rate)
            start=None
            for j,q in enumerate([x<.006 for x in rms]+[False]):
                if q and start is None:start=j
                elif not q and start is not None:
                    length=(j-start)*.01
                    if length>=.12:
                        cut=(ts[start]+ts[j-1])/2
                        choices.append({'cut':cut,'valley_start':ts[start]-.005,'valley_end':ts[j-1]+.005,'quiet_sec':length,'rms':sum(rms[start:j])/(j-start),'cost':-length+.02*abs(cut-(lo+hi)/2)})
                    start=None
            if not choices:raise AlignmentStop('Boundary %s: no >=120ms quiet valley between known words. No guessed cut.'%(i+1))
            rows.append({'left_anchor':left,'right_anchor':right,'scores':[float(segments[i][2]),float(segments[i+1][2])],'candidates':choices})
        # DP keeps the two best distinct paths per last candidate, permitting
        # a real runner-up ambiguity check without exponential enumeration.
        states=[(0.0,[],0.0)]
        for row in rows:
            nxt=[]
            for choice in row['candidates']:
                paths=[]
                for cost,path,last in states:
                    if choice['cut']-last>=.5:paths.append((cost+choice['cost'],path+[choice],choice['cut']))
                nxt.extend(sorted(paths,key=lambda x:x[0])[:2])
            states=nxt
            if not states:raise AlignmentStop('No monotonic joint cut path with nonempty cards.')
        states=[x for x in states if duration-x[2]>=.5]
        if not states:raise AlignmentStop('Final card too short after joint cuts.')
        states.sort(key=lambda x:x[0]);best=states[0]
        if len(states)>1 and states[1][0]-best[0]<.15:
            raise AlignmentStop('Joint cut ambiguity: two valley paths nearly tied. Use reviewed --cuts; no guessed cut.')
        for row,choice in zip(rows,best[1]):row['selected']=choice
        return [c['cut'] for c in best[1]],rows
    def latin_acoustic(self,master,texts,cache):
        """Mixed-language half: no transcript certification or guessed missing recovery."""
        from gemini_voice import read_wav,pauses
        rate,values=read_wav(master);duration=len(values)/rate
        gaps=pauses(rate,values)
        internal=[(a,b) for a,b in gaps if a>0 and b<len(values) and (b-a)/rate>=.8]
        if len(internal)!=len(texts)-1:
            raise AlignmentStop('Mixed-language audio has %s long internal pauses for %s card boundaries; cannot split safely. Originals retained, no guessed missing-card recovery.'%(len(internal),len(texts)-1))
        cuts=[(a+b)/2/rate for a,b in internal];edges=[0]+cuts+[duration]
        if any(b-a<.5 for a,b in zip(edges,edges[1:])):raise AlignmentStop('Mixed-language audio card too short; original retained.')
        cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
        result={'spoken_form_version':SP_NUMBER_REVISION,'engine':VERSION,'master_sha256':digest(master),'present_indices':list(range(len(texts))),'missing_indices':[],'cuts_sec':cuts,'scores':[],'transcript_char_match':None,'boundaries':[{'quiet_sec':(b-a)/rate,'selected':{'cut':c}} for (a,b),c in zip(internal,cuts)],'latin_spans_unverified':True,'entire_half_word_identity_unverified':True,'gates':'mixed-language acoustic pause split only; no transcript identity/absence certification','alignment_targets':[{'original':t,'spoken':spoken_form(t)[0],'mapping':spoken_form(t)[1]} for t in texts]}
        (cache/'ctc_alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result

    def analyze(self,master,texts,cache):
        if any(re.search(r'[A-Za-zÀ-ÖØ-öø-ÿ]',t) for t in texts):return self.latin_acoustic(master,texts,cache)
        original_texts=list(texts);spoken=[spoken_form(x) for x in texts]
        texts=self.check_texts(texts);a,rate,lp,greedy=self.infer(master,cache);duration=len(a)/rate
        fit=self.subset(lp,duration,texts,greedy)
        cuts,rows=self.joint_cuts(a,rate,fit['brackets'],fit['segments'])
        # Stability: keep the same present subset and compare alignment after
        # tiny time-origin perturbations. This is not a calibrated accuracy bound.
        for shift in (-1,1):
            import numpy as np
            pert=np.roll(lp,shift,axis=0);seg,b=self.align(pert,duration,[texts[i] for i in fit['selected']])
            if len(b)!=len(fit['brackets']) or any(abs(x-y)>.10 for pair,old in zip(b,fit['brackets']) for x,y in zip(pair,old)):
                raise AlignmentStop('Unstable boundary under one-frame perturbation. Originals kept.')
        result={'spoken_form_version':SP_NUMBER_REVISION,'alignment_targets':[{'original':x,'spoken':y[0],'mapping':y[1]} for x,y in zip(original_texts,spoken)],'engine':VERSION,'model_revision':REVISION,'master_sha256':digest(master),'greedy':greedy,'present_indices':fit['selected'],'missing_indices':fit['missing'],'transcript_char_match':fit['ratio'],'scores':[float(x[2]) for x in fit['segments']],'cuts_sec':cuts,'boundaries':rows,'gates':'provisional thresholds; card listening review still required'}
        (Path(cache)/'ctc_alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
