#!/usr/bin/env python3
"""Offline, truth-gated layout selection and successful-render coverage history.
No network, credentials, voice calls or renderer changes. Python standard library only.
"""
import collections, contextlib, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
VERSION = '1.0'
EXTRACTOR_REVISION = 'festival-time-venue-2+default-pool-1'
MAINS = ('hook','bignum','versus','date','group','place','quote','points','change','next','scale','engage')
STRIPS = ('stat','concept','place','phrase','calendar','track','units','waffle','chain','who','evidence','voiceprint','compare','roster','schedule','rule','result','money','contrast','movement','lawstage','verdict','hook','quote','incident')
LAT = str.maketrans('०१२३४५६७८९','0123456789')
UNCERTAIN = re.compile(r'होइन|छैन|हुँदैन|भएन|नगरे|नभए|नपरे|हल्ला|अफवाह|अपुष्ट|सम्भावना|सक्ने|सक्छ|प्रस्ताव|भएमा|यदि|आरोप|दाबी')
NUM = r'[०-९0-9]+(?:[.,][०-९0-9]+)*'


def digest(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)


@contextlib.contextmanager
def locked(root):
    d = Path(root)/'out'/'selection'; d.mkdir(parents=True,exist_ok=True)
    lock = d/'history.lock'
    for _ in range(100):
        try:
            fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError: time.sleep(.05)
    else: raise RuntimeError('Coverage history is busy or has a stale lock. Inspect out/selection/history.lock; history was not reset.')
    try:
        os.write(fd,str(os.getpid()).encode()); os.close(fd); yield d
    finally: lock.unlink(missing_ok=True)


def read_history(root):
    path=Path(root)/'out'/'selection'/'history.json'
    if not path.exists(): return {'version':VERSION,'reels':[],'used_total':{},'seen':{}}
    try:
        h=json.loads(path.read_text(encoding='utf-8'))
        if h.get('version')!=VERSION or not isinstance(h['reels'],list) or not isinstance(h['seen'],dict):raise ValueError('invalid schema')
        return h
    except Exception as e: raise RuntimeError('Cannot read coverage history; keeping it untouched: '+str(e))


def span(text, source):
    return isinstance(text,str) and bool(text.strip()) and text.strip() in source


def excerpt(cap, vo):
    # A workbook caption is a hint, never a source of new facts.
    return cap if span(cap,vo) else vo.strip()


def uncertain(vo): return bool(UNCERTAIN.search(vo)) or '?' in vo or '？' in vo


def numeric(vo, engine):
    # Only complete number+unit spans in narration qualify. Planner data cannot override narration.
    unit='|'.join(sorted(map(re.escape,engine.UNITS+('साता','हप्ता','जिल्ला','मत','अंक')),key=len,reverse=True))
    pat=re.compile(r'(?<![०-९0-9])'+NUM+r'\s*(?:'+unit+r')(?:\s*(?:रुपैयाँ|रुपियाँ|डलर))?')
    out=[]
    if re.search(NUM+r'\s*(?:रुपैयाँ|प्रतिशत|जना|वटा)बाट\s*'+NUM,vo):return []
    for m in pat.finditer(vo):
        value=m.group().strip(); pv=engine.parse_value(value)
        if m.start() and vo[m.start()-1] in '-−–—.':continue
        if re.search(r'(?:देखि|बीच|बाट)\s*$',vo[:m.start()]) or re.match(r'\s*(?:देखि|सम्म|बीच)',vo[m.end():]):continue
        if pv['num'] is None:continue
        # Reject compound amounts (e.g. १ करोड २० लाख), rather than silently taking a part.
        tail=vo[m.end():]
        if re.match(r'\s*'+NUM+r'\s*(?:लाख|करोड|हजार|सय)',tail):continue
        if m.start() and re.search(NUM+r'\s*(?:लाख|करोड|हजार|सय)\s*$',vo[:m.start()]):continue
        # Scope label to a complete clause containing this number. Never borrow another quantity's label.
        a=max(vo.rfind('।',0,m.start()),vo.rfind(',',0,m.start()))+1
        b=min([x for x in (vo.find('।',m.end()),vo.find(',',m.end())) if x>=0] or [len(vo)])
        label=vo[a:b].strip()
        out.append({'value':value,'label':label,'pv':pv,'start':m.start(),'end':m.end()})
    return out


def dates(vo, engine):
    pat=re.compile(r'(?<![\u0900-\u097fA-Za-z])('+ '|'.join(map(re.escape,engine.MONTH_NAMES))+r')\s*([०-९0-9]{1,2})\s*गते')
    return [{'month':m.group(1),'day':int(m.group(2).translate(LAT)),'value':m.group().strip(),'start':m.start(),'end':m.end()} for m in pat.finditer(vo) if 1<=int(m.group(2).translate(LAT))<=32]


def direct_quote(vo):
    # Quote marks alone do not establish a speaker. Require explicit contiguous name + ले ... भने/बताए.
    m=re.search(r'([\u0900-\u097f]+(?:\s+[\u0900-\u097f]+){0,3})ले\s*[“"‘](.+?)[”"’]\s*(?:भने|बताए)',vo)
    if not m:return None
    name=m.group(1).strip();claim=m.group(2).strip()
    if len(name.split())>3 or re.search(r'उनी|उनले|आरोप|दाबी|अनुसार',name):return None
    return {'name':name,'claim':claim}


def explicit_sequence(vo):
    m=re.search(r'पहिले\s+([^,।]+)[,।]\s*त्यसपछि\s+([^,।]+)',vo)
    if not m:return None
    chunks=[m.group(1).strip(),m.group(2).strip()]
    if any(len(x.split())>6 for x in chunks):return None
    return chunks


def explicit_law(vo):
    if uncertain(vo):return None
    if not re.search(r'विधेयक|कानून|ऐन',vo):return None
    # Each status is proved independently; an earlier mention is never presumed completed.
    stages=[]
    for institution in ('प्रतिनिधिसभा','राष्ट्रिय सभा','राष्ट्रपति'):
        m=re.search(re.escape(institution)+r'(?:मा|ले|बाट)?\s*(?:विधेयक\s*)?(पारित|प्रमाणीकरण|पठाइनेछ|पठाइएको|दर्ता)',vo)
        if m:
            stages.append({'text':m.group().strip(),'done':m.group(1) in ('पारित','प्रमाणीकरण','पठाइएको','दर्ता'),'pos':m.start()})
    if len(stages)<2:return None
    stages.sort(key=lambda x:x.pop('pos'))
    return {'kind':'lawstage','stages':stages,'vo':vo}


def change_fact(vo):
    m=re.search(r'(?P<old>'+NUM+r'\s*(?:रुपैयाँ|प्रतिशत|जना|वटा))बाट\s*(?P<new>'+NUM+r'\s*(?:रुपैयाँ|प्रतिशत|जना|वटा))\s*(?:पुगेको|पुग्यो|बढ्यो|घट्यो|भएको)',vo)
    if not m or uncertain(vo):return None
    if re.sub(NUM,'',m['old']).strip()!=re.sub(NUM,'',m['new']).strip():return None
    return m['old'],m['new']


def true_points(vo):
    # Only visibly enumerated, complete statements. A comma-separated noun list is not a list of claims.
    parts=re.split(r'(?:पहिलो|दोस्रो|तेस्रो)\s*[:：]\s*',vo)
    if len(parts)<3:return []
    out=[p.strip(' ।') for p in parts[1:]]
    return out if 2<=len(out)<=3 and all(span(p,vo) and len(p.split())>=2 for p in out) else []


def provenance(payload, vo, skip=()):
    out=[]
    def walk(x,k=''):
        if k in skip:return
        if isinstance(x,str) and x.strip():
            t=x.strip();a=vo.find(t)
            if a<0:raise ValueError('Unsupported span '+repr(t))
            out.append({'field':k,'text':t,'start':a,'end':a+len(t)})
        elif isinstance(x,list):
            for v in x:walk(v,k)
        elif isinstance(x,dict):
            for kk,v in x.items():walk(v,kk)
    walk(payload)
    return out



def named_venues(vo):
    # An explicit named venue with a locality suffix, never an inferred city/address.
    out=[]
    for m in re.finditer(r'([\u0900-\u097f]+(?:\s+[\u0900-\u097f]+){0,2})\s+(मन्दिर|मंदिर|विद्यालय|अस्पताल|रंगशाला|सभा हल|पार्क)(?:मा|बाट|सम्म)',vo):
        words=m.group(1).split()
        if any(w.endswith(('को','का','की','मा','ले','बाट','पछि')) for w in words):
            words=words[next((i+1 for i in range(len(words)-1,-1,-1) if words[i].endswith(('को','का','की','मा','ले','बाट','पछि'))),0):]
        if not words or any(w in ('यस','यो','उक्त','विभिन्न','नजिकको','नयाँ','मन्दिर') for w in words):continue
        name=' '.join(words)+' '+m.group(2)
        if span(name,vo) and name not in out:out.append(name)
    return out


def named_period(vo):
    # Festival markers are names, NOT converted into calendar dates or weekdays.
    m=re.search(r'((?:घटस्थापना|अष्टमी|नवमी|महानवमी|दशमी|पूर्णिमा|एकादशी))देखि\s*((?:घटस्थापना|अष्टमी|नवमी|महानवमी|दशमी|पूर्णिमा|एकादशी))सम्म',vo)
    return (m.group(1),m.group(2)) if m and m.group(1)!=m.group(2) else None


def clock_events(vo):
    # Only explicit clock syntax; each time owns its adjacent action clause.
    events=[]
    clauses=re.split(r'[,।]|\s+र\s+',vo)
    for clause in clauses:
        m=re.search(r'(बिहान|दिउँसो|साँझ|राति)\s*([०-९0-9]{1,2})\s*बजे(?:देखि)?',clause)
        if not m or not 1<=int(m.group(2).translate(LAT))<=12:continue
        if re.search(r'छैन|हुँदैन|नहुने|होइन|भएन|यदि|भएमा|हल्ला|अपुष्ट',clause):continue
        text=clause[m.end():].strip()
        before=clause[:m.start()].strip()
        # Keep both subject and predicate contiguous separately, not an invented stitched claim.
        if not text or not re.search(r'सुरु|खुला|खुल्ने|बन्द|हुनेछ|गरिनेछ|भेट|आयोजना',text):continue
        events.append({'time':m.group().strip(),'text':clause.strip(),'subject':before})
    return events


def explicit_items(vo):
    # Named shared-role items, not causal stages or arbitrary comma fragments.
    m=re.search(r'(?:महोत्सवमा|कार्यक्रममा|प्रदर्शनीमा|मेलामा)\s+(.+?)\s+(मुख्य आकर्षण|मुख्य कार्यक्रम)(?:\s|।)',vo)
    if not m or uncertain(vo):return []
    items=[x.strip() for x in re.split(r'\s+र\s+|\s+तथा\s+|,',m.group(1))]
    return items if 2<=len(items)<=3 and all(span(x,vo) and 2<=len(x.split())<=7 for x in items) else []

def candidates(vo, cap, idx, engine, default=None):
    mains=[]; strips=[]; failures=[]
    title=excerpt(cap,vo); nums=[] if uncertain(vo) else numeric(vo,engine);ds=dates(vo,engine);pl=engine.find_places(vo)
    def main(kind,payload,score,reason):
        try:
            ev=provenance(payload,vo,('type','dark','value','decimals','day','year','weekday','prefix','unit','hi','kicker','plain_fallback'))
            mains.append({'kind':kind,'payload':dict(payload,type=kind,vo=vo),'score':score,'reason':reason,'evidence':ev})
        except ValueError as e:failures.append({'design':'main:'+kind,'reason':'validator: '+str(e)})
    def strip(g,score,reason):
        if not g:return
        try:
            k=g['kind'];ev=provenance(g,vo,('kind','vo','direction','icon','done','focus','n','total','day'))
            # The existing emitter schema is also checked before accepting.
            engine.MAKERS[k](g,True)
            strips.append({'kind':k,'payload':g,'score':score,'reason':reason,'evidence':ev})
        except (ValueError,KeyError,TypeError,IndexError) as e:failures.append({'design':'strip:'+g.get('kind','?'),'reason':'validator: '+str(e)})
    if idx==0:
        main('hook',{'headline':title,'sub':''},100,'opening statement')
    else:
        main('points',{'title':vo,'points':[],'plain_fallback':True},45,'approved full-sentence neutral fallback')
        if len(vo)>360:failures.append({'design':'main:points_plain','reason':'fit: long fallback requires preview inspection'})
        pts=true_points(vo)
        if pts:main('points',{'title':'','points':pts},90,'explicit enumerated claims')
        for n in nums:
            pv=n['pv']
            if len(nums)>1:continue  # Comparable pairs/change have their own unambiguous contracts.
            # Approximation qualifiers stay visible with Scale; never count an approximate amount as exact.
            pre=vo[max(0,n['start']-12):n['start']]
            approximate=re.search(r'(करिब|झण्डै|साढे|पौने|देढ)\s*$',pre)
            if approximate:continue  # Preserve the full claim using a neutral card, rather than an exact figure.
            main('bignum',{'value':pv['num'],'unit':pv['unit'],'prefix':pv['prefix'],'decimals':pv['decimals'],'label':n['label'],'sub':''},86,'narrated quantity with exact unit')
            main('scale',{'number':n['value'],'headline':n['label'],'sub':''},86,'narrated quantity, non-counting')
        for d in ds:
            main('date',{'month':d['month'],'day':d['day'],'headline':title,'weekday':''},92,'explicit month/day, no inferred weekday/year')
        if len(pl)==1 and re.search(re.escape(pl[0]['ne'])+r'(?:मा|स्थित|बाट|सम्म|का\s+विभिन्न\s+स्थानमा)',vo):main('place',{'place':pl[0]['ne'],'headline':title},84,'one explicit location')
        q=direct_quote(vo)
        if q:main('quote',{'quote':q['claim'],'name':q['name'],'role':''},94,'verbatim quotation with explicit speaker')
        ch=change_fact(vo)
        if ch:main('change',{'old':ch[0],'new':ch[1],'label':title},94,'explicit same-unit old-to-new change')
        comp=engine.plan_compare(vo)
        if comp and not uncertain(vo):
            if re.sub(NUM,'',comp['left']).strip()==re.sub(NUM,'',comp['right']).strip():
                main('versus',{'left':{'label':comp['leftMeta'],'value':comp['left']},'right':{'label':comp['rightMeta'],'value':comp['right']}},92,'explicit comparable quantities')
                main('group',{'headline':'','rows':[{'label':comp['leftMeta'],'value':comp['left']},{'label':comp['rightMeta'],'value':comp['right']}]},92,'named quantitative ledger')
        roster=engine.plan_roster(vo)
        if roster and not uncertain(vo) and len(roster['members'])<=4:
            main('group',{'headline':roster.get('title',''),'rows':[{'label':m,'value':''} for m in roster['members'][:4]]},90,'explicit roster, no invented values')
        if ds and re.search(r'हुनेछ|गरिनेछ|खुल्नेछ|सुरु हुनेछ',vo) and not uncertain(vo):
            steps=[]
            for d in ds[:3]:
                a=d['end']; b=min([x for x in (vo.find(',',a),vo.find('।',a)) if x>=0] or [len(vo)])
                text=vo[a:b].strip()
                if text:steps.append({'date':d['value'],'text':text})
            if steps:main('next',{'kicker':'','headline':title,'steps':steps},92,'explicit dated future action')
    venues=named_venues(vo)
    if len(venues)==1:
        if idx>0:main('place',{'place':venues[0],'headline':title},90,'explicit named venue')
        strip({'kind':'place','places':[{'ne':venues[0]}],'vo':vo},88,'explicit named venue, no inferred route')
    period=named_period(vo)
    if period and not uncertain(vo):
        strip({'kind':'schedule','start':period[0],'end':period[1],'connector':'देखि','vo':vo},94,'explicit named festival period, no invented calendar date')
        if idx>0:main('next',{'kicker':'','headline':title,'steps':[{'date':period[0]+'देखि','text':period[1]+'सम्म'}]},86,'literal named festival period, no calendar inference')
    events=clock_events(vo)
    if events and all(len(e['text'])<=100 for e in events):
        if idx>0:
            main('next',{'kicker':'','headline':'','steps':[{'date':e['time'],'text':e['text']} for e in events]},96,'explicit clock time/action pairs')
            if len(events)>=2 and all(e['subject'] and len(e['subject'])<=16 for e in events):
                main('group',{'headline':'','rows':[{'label':e['time'],'value':e['subject'] or e['text']} for e in events]},88,'independent timed event rows')
        # Never draw an arrow between two different events as if it were one duration.
        e=events[0]
        strip({'kind':'schedule','start':e['time'],'vo':vo},88,'one narrated clock marker, not an invented event interval')
    items=explicit_items(vo)
    if items:
        if idx>0:main('points',{'title':'मुख्य आकर्षण' if 'मुख्य आकर्षण' in vo else 'मुख्य कार्यक्रम','points':items},96,'explicit shared-role attraction list')
        strip({'kind':'roster','title':'मुख्य आकर्षण' if 'मुख्य आकर्षण' in vo else 'मुख्य कार्यक्रम','members':items,'vo':vo},92,'explicit shared-role items, no causal arrows')
    dq=direct_quote(vo)
    if dq:
        strip({'kind':'quote','speaker':dq['name'],'claim':dq['claim'],'vo':vo},94,'direct quotation with explicit speaker')
    vm=re.search(r'(प्रधानमन्त्री|मन्त्री|निर्देशक|अध्यक्ष|प्रवक्ता)\s+([\u0900-\u097f]+(?:\s+[\u0900-\u097f]+){0,2})ले\s+(.+?)\s+(भने|बताए|उल्लेख गरे|स्पष्ट पारे)',vo)
    if vm:
        name=vm.group(2);claim=vm.group(3)
        if not re.search(r'उनी|उनले|आरोप|दाबी',name):
            strip({'kind':'voiceprint','name':name,'role':vm.group(1),'parts':[{'t':claim,'hl':True}],'hl':claim,'vo':vo},94,'named role and explicitly attributed speech')
    rm=re.search(r'(टोलीमा|टिममा)\s+([^।]+)',vo)
    if rm and not uncertain(vo):
        segment=re.sub(r'\s+(?:छन्|छ|समावेश छन्)\s*$', '',rm.group(2).strip())
        members=[x.strip() for x in re.split(r',|\s+र\s+',segment)]
        if 3<=len(members)<=10 and all(1<=len(x.split())<=3 and re.fullmatch(r'[\u0900-\u097f ]+',x) and span(x,vo) for x in members):
            strip({'kind':'roster','title':'','members':members,'vo':vo},92,'explicit team member enumeration')
            if idx>0 and len(members)<=4:main('group',{'headline':'','rows':[{'label':x,'value':''} for x in members[:4]]},90,'explicit roster')
    cast=re.search(r'(अभिनेता|अभिनेत्री)\s+([\u0900-\u097f]+(?:\s+[\u0900-\u097f]+){0,2})\s+र\s+(अभिनेता|अभिनेत्री)\s+([\u0900-\u097f]+(?:\s+[\u0900-\u097f]+){0,2})\s+मुख्य भूमिकामा',vo)
    if cast and not uncertain(vo):
        members=[cast.group(2).strip(),cast.group(4).strip()]
        strip({'kind':'roster','members':members,'title':'मुख्य भूमिकामा','vo':vo},92,'explicitly named principal cast')
        if idx>0:main('group',{'headline':'मुख्य भूमिकामा','rows':[{'label':cast.group(1),'value':members[0]},{'label':cast.group(3),'value':members[1]}]},90,'explicit actor-role pairs')
    after=re.search(r'छायांकन\s+सकिएपछि\s+(पोस्ट प्रोडक्सनको काम)\s+अघि बढ्नेछ',vo)
    if after:
        strip({'kind':'concept','nodes':[{'ne':'छायांकन'},{'ne':after.group(1)}],'vo':vo},92,'explicit production-stage order, not an invented cause')
    verdict=re.search(r'(विशेष अदालत|अदालत|फिफा|आईसीसी|सरकार|अख्तियार)ले\s+([\u0900-\u097f]+(?:\s+[\u0900-\u097f]+){0,2})लाई\s+(दोषी ठहर|निलम्बन|प्रतिबन्ध)\s+(?:गरेको|गरेको छ|लगाएको|गरे)',vo)
    if verdict and not uncertain(vo):
        strip({'kind':'verdict','subject':verdict.group(2),'decision':verdict.group(3),'authority':verdict.group(1),'vo':vo},94,'explicit authority, target and final decision')
    if not uncertain(vo):
        for n in nums:
            if len(nums)>1:continue
            if re.search(r'रुपैयाँ|रुपियाँ|डलर',n['value']):
                before=vo[:n['start']].strip(' ।,');after=vo[n['end']:].strip(' ।,')
                ctx=before if 1<=len(before.split())<=6 else after
                if span(ctx,vo) and re.search(r'बजेट|आम्दानी|खर्च|मूल्य|घाटा|ऋण|नाफा|लागत',ctx):
                    strip({'kind':'money','amount':n['value'],'context':ctx,'direction':'','compare':'','vo':vo},90,'explicit amount and financial context, no inferred cash-flow direction')
    # Existing text detectors are candidates, no first-match priority. Reject negated/conditional relational visuals.
    parser_names=('who','compare','schedule','rule','result','contrast','movement','incident')
    for k in parser_names:
        if uncertain(vo) and k not in ('rule','quote','voiceprint','schedule'):continue
        if k=='schedule' and not ds:continue
        if k=='rule' and not re.search(r'यदि.+भने',vo):continue
        if k=='quote' and dq:continue
        if k=='quote':
            # Indirect attributed claims may use the claim strip, never quotation marks in the main quote card.
            g=engine.plan_quote(vo)
        else:g=getattr(engine,'plan_'+k)(vo)
        if not g:continue
        if k=='voiceprint' and not re.search(r'भने|बताए|उल्लेख|स्पष्ट पारे',vo):continue
        if k=='verdict' and (not re.search(r'\S+(?:लाई|माथि)',vo) or not re.search(r'अदालत|फिफा|आईसीसी|सरकार|अख्तियार',vo) or not re.search(r'गरेको|गरेको छ|लगाएको|ठहर',vo)):continue
        if k=='incident':
            event=next((w for w in ('पहिरो','शव','उद्धार','दुर्घटना','वर्षा','आगलागी') if w in vo),'')
            event_clause=next((x for x in re.split(r'[,।]',vo) if event in x),'')
            if g.get('count') and g['count'] not in event_clause:continue
        if k=='movement' and not re.search(r'गए|रवाना|सरे|जाने',vo):continue
        if k=='compare' and re.sub(NUM,'',g['left']).strip()!=re.sub(NUM,'',g['right']).strip():continue
        # Drop non-rendered parser metadata, not unsupported displayed text.
        if k=='voiceprint':g={key:value for key,value in g.items() if key not in ('org',)}
        strip(g,88,'explicit '+k+' relation')
    if not uncertain(vo) and not re.search(r'भने|बताए|अनुसार|दाबी',vo):
        strip(engine.plan_chain(vo,''),90,'asserted cause and effect')
        strip(explicit_law(vo),92,'individually stated legal stages')
    seq=explicit_sequence(vo)
    if seq and not uncertain(vo):strip({'kind':'concept','nodes':[{'ne':s} for s in seq],'vo':vo},92,'explicit ordered sequence')
    if pl and any(re.search(re.escape(x['ne'])+r'(?:मा|स्थित|बाट|सम्म|का\s+विभिन्न\s+स्थानमा)',vo) for x in pl):
        # Two pins are linked by the existing design. Do not turn two unrelated location mentions into a route.
        route=engine.route_ends(vo)
        places=pl if len(pl)==1 or all(route) else pl[:1]
        strip({'kind':'place','places':places,'vo':vo},82,'explicit location; linked pair only with route words')
    for d in ds:
        if d['day']>25:continue  # Neighbor tiles must not imply impossible end-of-month dates.
        strip({'kind':'calendar','month':d['month'],'day':d['day'],'value':d['value'],'label':d['value'],'icon':'calendar','vo':vo},86,'explicit date; neighboring day tiles are diagram context')
    for n in nums:
        if len(nums)>1:continue
        pv=n['pv'];base={'value':n['value'],'label':n['label'],'cap':'','vo':vo}
        if re.search(r'(करिब|झण्डै|साढे|पौने|देढ)\s*$',vo[max(0,n['start']-12):n['start']]):continue
        strip(dict(base,kind='stat'),82,'narrated quantity')
        if pv['percent'] is not None:
            strip(dict(base,kind='waffle'),86,'explicit percentage share')
        if len(nums)==1 and pv['num'].is_integer() and 2<=pv['num']<=48 and re.match(r'जना|वटा|ओटा|जिल्ला|घर|परिवार|सिट',pv['unit']):
            strip(dict(base,kind='units',n=int(pv['num']),icon='people' if pv['unit'].startswith('जना') else 'pin'),86,'explicit countable objects')
        fr,to=engine.route_ends(vo)
        if pv['unit'].startswith(('किलोमिटर','किमि','मिटर')) and fr and to and not uncertain(vo):
            strip(dict(base,label=pv['unit'],kind='track',total=pv['num'],unit=pv['unit'],frm=fr,to=to),90,'explicit distance and route endpoints')
    q=engine.plan_hook(vo)
    if q:strip(q,88,'explicit question')
    if len(title.split())<=8:
        strip({'kind':'phrase','text':title,'icon':engine.icon_for(title),'vo':vo},60,'literal short statement, no inferred relationship')
    strip(engine.plan_evidence(vo,title),60,'literal narration with emphasis')
    if default:
        # The converter's own card/strip for this line is always an allowed option, so a story
        # never ends up worse than today's output. It is trusted converter output, not re-gated.
        dm,dg=default
        if dm:
            sc=101 if idx==0 else 85 if dm['type'] in ('bignum','scale') else 45
            mains.append({'kind':dm['type'],'payload':dict(dm,km_default=True,vo=vo),'score':sc,'reason':'converter default card','evidence':[],'default':True})
        if dg:
            try:
                engine.MAKERS[dg['kind']](dg,True)
                strips.append({'kind':dg['kind'],'payload':dg,'score':60 if dg['kind'] in ('phrase','evidence') else 84,'reason':'converter default strip','evidence':[],'default':True})
            except Exception as e:failures.append({'design':'strip:default','reason':'default strip not drawable: '+str(e)})
    return mains,strips,failures


def mainkey_of(c):
    if c.get('plain_fallback') or (c.get('km_default') and c.get('type')=='points'):return 'main:points_plain'
    return 'main:'+c['type']


def choose(mains,strips,history,previous):
    last=history.get('reels',[])[-20:];counts=collections.Counter()
    for r in last:counts.update(r['selected'])
    pairs=[]
    def nonrepeat(items,prefix):
        # Avoid an immediate repeat only when a comparably good alternative exists (within 10 points).
        alt=[x for x in items if previous.get(prefix)!=x['kind']]
        if alt and max(x['score'] for x in alt)>=max(x['score'] for x in items)-10:return alt
        return items
    mains=nonrepeat(mains,'main');strips=nonrepeat(strips,'strip')
    for m in mains:
        for s in strips:
            score=m['score']+s['score']; penalties=[]
            # Complement rather than duplicating the same fact twice.
            if m['kind']==s['kind'] or (m['kind'] in ('bignum','scale') and s['kind']=='stat'):
                score-=22;penalties.append('duplicate emphasis')
            for prefix,c in (('main',m),('strip',s)):
                key=prefix+':'+c['kind']
                if mainkey_of(m['payload'])=='main:points_plain' and prefix=='main':key='main:points_plain'
                # Max rarity bonus 8%, never stronger than a 10-point meaning gap on that side.
                score+=c['score']*.08/(1+counts[key])
                if previous.get(prefix)==c['kind']:score-=8;penalties.append('adjacent repetition')
            pairs.append((score,m['kind'],s['kind'],m,s,penalties,(1 if m.get('default') else 0)+(1 if s.get('default') else 0)))
    if not pairs:raise ValueError('No validated candidate pair')
    best=max(pairs,key=lambda p:(round(p[0],6),p[6],p[1],p[2]))
    return best[3],best[4],round(best[0],3),best[5]


def select_story(story,pkg,engine,root):
    with locked(root):history=read_history(root)
    report=[];previous={};selected=[];elig=[];misses=[]
    content_hash=digest([(c.get('vo',''),c.get('voice_tone','neutral')) for c in story['cards']])
    cache_path=Path(root)/'out'/'selection'/'plans'/(digest([story['id'],content_hash,EXTRACTOR_REVISION])+'.json')
    if cache_path.exists():
        cached=json.loads(cache_path.read_text(encoding='utf-8'))
        if cached.get('selection',{}).get('extractor_revision')!=EXTRACTOR_REVISION or cached.get('selection',{}).get('content_hash')!=content_hash or cached['id']!=story['id']:raise ValueError('Invalid saved selection plan; untouched')
        return cached
    # Exclude this story's own prior render from its recency calculation: reruns stay stable.
    history=dict(history,reels=[r for r in history['reels'] if r['id']!=story['id']])
    for idx,c in enumerate(story['cards']):
        vo=c['vo']
        if c['type']=='engage':
            selected.append('main:engage');elig.append('main:engage')
            report.append({'line':idx+1,'selected_main':'engage','selected_strip':'none','reason':'original engagement wording preserved','eligible':['main:engage'],'evidence':[]});continue
        # Existing caption may be useful only if it is an exact narration span.
        cap=c.get('headline') or c.get('title') or c.get('sub') or ''
        cap=cap.replace('{{','').replace('}}','')
        mains,strips,fail=candidates(vo,cap,idx,engine,(({k:v for k,v in c.items() if k not in ('strip','vo','voice_tone','km_default')}),(c.get('strip') or {}).get('_gen')))
        m,s,score,pen=choose(mains,strips,history,previous)
        mainkey=mainkey_of(m['payload'])
        lineelig=sorted(set([mainkey_of(a['payload']) for a in mains]+['strip:'+a['kind'] for a in strips]))
        if mainkey=='main:points_plain':fail.append({'design':'main:points_plain','reason':'extractor limitation or no supported structure: inspect extraction_signals; no rich main candidate selected'})
        old=c.copy();c.clear();c.update(m['payload']);c['dark']=True;c['voice_tone']=old.get('voice_tone','neutral')
        c['strip']={'kind':'graphic','label':'','src':'','_gen':s['payload']}
        print('  selection',idx+1,'->',mainkey.split(':')[1],'+',s['kind'],'('+m['reason']+'; '+s['reason']+')')
        selected.extend([mainkey,'strip:'+s['kind']]);elig.extend(lineelig);misses.extend(fail)
        previous={'main':m['kind'],'strip':s['kind']}
        report.append({'line':idx+1,'selected_main':mainkey.split(':')[1],'selected_strip':s['kind'],'score':score,'reason':[m['reason'],s['reason']],'penalties':pen,'eligible':lineelig,'evidence':{'main':m['evidence'],'strip':s['evidence']},'rejected':fail,'extraction_signals':{'clock_markers':bool(re.search(r'बजे',vo)),'named_period_markers':bool(re.search(r'देखि.+सम्म',vo)),'venue_markers':bool(re.search(r'मन्दिर|विद्यालय|अस्पताल|रंगशाला|पार्क',vo)),'shared_role_markers':bool(re.search(r'मुख्य आकर्षण|मुख्य कार्यक्रम',vo))},'missed_reasons':{k:'fit/repetition/rarity: another legal pair scored higher' for k in lineelig if k not in (mainkey,'strip:'+s['kind'])}})
    story['selection']={'extractor_revision':EXTRACTOR_REVISION,'version':VERSION,'content_hash':content_hash,'plan_hash':digest([(c['type'],{k:v for k,v in c.items() if k not in ('strip','vo','voice_tone')},c.get('strip',{}).get('_gen')) for c in story['cards']]),'selected':selected,'eligible':sorted(set(elig)),'lines':report,'extractor_failures':misses,'status':'planned','not_eligible':{k:'source structure absent or extractor could not prove required meaning' for k in ['main:'+x for x in MAINS]+['strip:'+x for x in STRIPS] if k not in elig}}
    atomic(cache_path,story)
    return story


def coverage(history):
    keys=['main:'+x for x in MAINS]+['main:points_plain']+['strip:'+x for x in STRIPS]
    last=history['reels'][-20:];matrix={};stats={}
    for k in keys:
        used=sum(r['selected'].count(k) for r in last)
        eligible=sum(k in r['eligible'] for r in last)
        selected=sum(k in r['selected'] for r in last)
        stats[k]={'used_total':history['used_total'].get(k,0),'used_last_20':used,'eligible_last_20':eligible,'selected_last_20':selected,'missed_reasons':[r.get('missed',{}).get(k,'eligible but another pair selected') for r in last if k in r['eligible'] and k not in r['selected']],'state':'used' if used else ('eligible but unused' if eligible else 'not tested / no proven eligible source')}
        matrix[k]=['selected' if k in r['selected'] else 'eligible' if k in r['eligible'] else 'not proven eligible' for r in last]
    return {'version':VERSION,'rendered_reels':[r['id'] for r in last],'designs':stats,'matrix':matrix}


def validate_media(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size==0:raise ValueError('rendered output missing or empty')
    r=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True)
    if r.returncode:raise ValueError('ffprobe could not validate rendered output')
    p=json.loads(r.stdout)
    if not any(s.get('codec_type')=='video' for s in p.get('streams',[])) or float(p.get('format',{}).get('duration',0))<=0:raise ValueError('no positive-duration video')


def commit(story_path,video,root):
    story=json.loads(Path(story_path).read_text(encoding='utf-8-sig'));sel=story.get('selection')
    if not sel:return False  # Legacy stories remain renderable; never invent historical eligibility.
    if sel.get('version')!=VERSION:raise ValueError('unsupported selection version')
    if sel['content_hash']!=digest([(c.get('vo',''),c.get('voice_tone','neutral')) for c in story['cards']]):raise ValueError('Narration changed after planning; history not committed')
    if sel.get('render_seal')!=digest(story['cards']):raise ValueError('Story fields changed after conversion; history not committed')
    actual=[]
    for c in story['cards']:
        actual.append(mainkey_of(c))
        if c['type']!='engage':actual.append('strip:'+c['strip']['anim']['kind'])
    if actual!=sel['selected']:raise ValueError('Rendered layout differs from plan; history not committed')
    validate_media(video)
    ident=story['id']+':'+sel['content_hash']
    with locked(root) as d:
        h=read_history(root)
        if ident in h['seen']:
            if h['seen'][ident]!=sel['plan_hash']:raise ValueError('Same story/content already rendered with a different plan; no duplicate usage counted')
            return False
        for k in actual:h['used_total'][k]=h['used_total'].get(k,0)+1
        miss={}
        for ln in sel['lines']:miss.update(ln.get('missed_reasons',{}))
        h['reels'].append({'id':story['id'],'content_hash':sel['content_hash'],'plan_hash':sel['plan_hash'],'selected':actual,'eligible':sel['eligible'],'missed':miss,'rendered_at':time.time()})
        h['reels']=h['reels'][-20:];h['seen'][ident]=sel['plan_hash']
        atomic(d/'history.json',h);atomic(d/'coverage.json',coverage(h))
    return True


def main():
    if len(sys.argv)==4 and sys.argv[1]=='commit':
        root=Path(__file__).resolve().parent.parent
        try:changed=commit(sys.argv[2],sys.argv[3],root)
        except Exception as e:
            print('NOTE: variety history not updated: '+str(e)[:200]);return 0
        print('Selection coverage: '+('successful render recorded' if changed else 'already counted or legacy story; no duplicate usage'));return 0
    if len(sys.argv)==2 and sys.argv[1]=='report':
        print(json.dumps(coverage(read_history(Path(__file__).resolve().parent.parent)),ensure_ascii=False,indent=2));return 0
    print('Usage: py scripts/km_selection.py report | commit stories/ID.json out/ID.mp4');return 2

if __name__=='__main__':sys.exit(main())
