#!/usr/bin/env python3
"""One durable at-most-once aggregate WhatsApp notification per reel.
No automatic retry after an uncertain send. Claims/results stay in the repo.
"""
import json, os, pathlib, re, sys, urllib.error, urllib.request
import km_state
ROOT = km_state.ROOT
RESULT = pathlib.Path('/tmp/km_publish_result.txt')

def summaries():
    ids = set()
    runlog = pathlib.Path('/tmp/km_run.log')
    if runlog.exists():
        ids.update(re.findall(r'^SELECTED ONLY: ([A-Za-z0-9_-]+)$',runlog.read_text(errors='replace'),re.M))
    drive = pathlib.Path('/tmp/km_drive')
    uploaded = set()
    if drive.exists():
        for line in drive.read_text().splitlines():
            if line.startswith('ok '): uploaded.add(line[3:].removesuffix('.mp4'))
    ids.update(uploaded)
    rows = {}
    if RESULT.exists():
        for line in RESULT.read_text().splitlines():
            parts = line.split(' ',3)
            if len(parts) < 3: continue
            kind,sid,network = parts[:3]
            if not re.fullmatch(r'[A-Za-z0-9_-]+',sid): continue
            ids.add(sid); rows.setdefault(sid,{})[network] = kind
    if not ids and os.environ.get('KM_JOB_STATUS') == 'failure':
        run_id = os.environ.get('GITHUB_RUN_ID','')
        if re.fullmatch(r'[0-9]+',run_id):
            yield 'RUN_'+run_id, 'Reel run stopped before a reel was identified. Check GitHub Actions summary and saved logs. No blind rerun.'
    for sid in sorted(ids):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',sid): continue
        title = ''
        row = ROOT/'inbox'/sid/'row.json'
        if row.is_file():
            try: title = str(json.loads(row.read_text()).get('headline',''))[:200]
            except (ValueError,OSError): pass
        lines = ['Reel '+sid+(' - '+title if title else '')]
        if sid in uploaded: lines.append('Drive copy is ready.')
        groups = {}
        for n,k in rows.get(sid,{}).items(): groups.setdefault(k,[]).append(n)
        for k,label in [('accepted','Submission accepted (final delivery not checked)'),
                        ('skipped','Previously accepted; not sent again'),
                        ('failed','Not submitted; safety/connection check needed'),('unknown','Submission outcome uncertain; inspect before retry'),('dry_run','Read-only check')]:
            if groups.get(k): lines.append(label+': '+', '.join(groups[k])+'.')
        if not rows.get(sid): lines.append('Posting deferred or reel incomplete. Check the saved run/state logs first.')
        lines.append('Details: GitHub Actions summary and km-state artifact.')
        yield sid,'\n'.join(lines)

def _title(sid):
    row = ROOT/'inbox'/sid/'row.json'
    if row.is_file():
        try:return str(json.loads(row.read_text()).get('headline',''))[:200]
        except (ValueError,OSError):pass
    return ''

def _drive_failures():
    drive = pathlib.Path('/tmp/km_drive')
    failed = set()
    if drive.exists():
        for line in drive.read_text(errors='replace').splitlines():
            if line.startswith('failed '):
                name=line[7:].strip()
                if name.endswith('.mp4'):name=name[:-4]
                if re.fullmatch(r'[A-Za-z0-9_-]+',name):failed.add(name)
    return failed

def _run_published_candidates():
    """Use this run's post receipts if a remote state lookup is unavailable."""
    if not RESULT.is_file():return set()
    enabled={'tiktok','youtube','linkedin'}
    if os.environ.get('META_ENABLE','false').lower()=='true':enabled.update(('facebook','instagram','threads'))
    seen={}
    try:lines=RESULT.read_text(errors='replace').splitlines()
    except OSError:return set()
    for line in lines:
        parts=line.split(' ',3)
        if len(parts)<3 or not re.fullmatch(r'[A-Za-z0-9_-]+',parts[1]):continue
        kind,sid,network=parts[:3]
        if network in enabled:seen.setdefault(sid,{})[network]=kind
    return {sid for sid,rows in seen.items()
            if set(rows)==enabled and all(rows[n] in ('accepted','skipped') for n in enabled)}

def events():
    rows=list(summaries())
    ids={sid for sid,_ in rows}
    drive_failed=_drive_failures();ids.update(drive_failed)
    try:published=set(km_state.published_candidates())
    except Exception as e:
        print('Published-status lookup unavailable:',type(e).__name__)
        published=set()
    # A current-run accepted result is already preceded by its durable receipt
    # write. This keeps the per-reel success notice available if the next read
    # of main is briefly unavailable, while still requiring every channel.
    published.update(_run_published_candidates())
    ids.update(published)
    for sid in sorted(ids):
        if sid in published:
            title=_title(sid)
            networks=('tiktok','youtube','linkedin')
            if os.environ.get('META_ENABLE','false').lower()=='true':networks+=('facebook','instagram','threads')
            body='Reel '+sid+(' - '+title if title else '')+'\nPost submission was accepted on all '+str(len(networks))+' enabled platforms.'
            yield sid,'published',body
        elif sid in drive_failed:
            title=_title(sid)
            body='Reel '+sid+(' - '+title if title else '')+'\nGoogle Drive upload failed after three automatic retries. The saved render will be reused on a later run; this GitHub run is marked failed.'
            yield sid,'drive_failure',body
        else:
            body=next((text for key,text in rows if key==sid),'Reel '+sid+' was not fully posted in this run. Check the GitHub Actions summary.')
            yield sid,'summary',body

def send(sid, body, event='summary'):
    token = os.environ.get('WA_TOKEN',''); phone = os.environ.get('WA_PHONE_ID',''); to = os.environ.get('WA_TO','')
    if not (token and phone and to):
        print('WA credentials missing; no claim or message created'); return
    try: path,owner = km_state.notification_claim(sid,body,event=event)
    except km_state.StateError as e:
        print('Notification suppressed:',str(e)); return
    payload = {'messaging_product':'whatsapp','to':to,'type':'text','text':{'body':body}}
    req = urllib.request.Request('https://graph.facebook.com/v21.0/'+phone+'/messages',
          data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    state='uncertain'; mid=''
    try:
        with urllib.request.urlopen(req,timeout=30) as r: obj=json.loads(r.read())
        mid=str(obj.get('messages',[{}])[0].get('id','')); state='sent' if mid else 'uncertain'
    except urllib.error.HTTPError as e:
        # These HTTP responses are explicit provider rejections; a later run
        # may safely retry the event with the same durable event key.
        if e.code in (400,401,403,404,413,422,429):
            state='failed'
            print('WhatsApp rejected notification with HTTP',e.code)
        else:
            print('WhatsApp send outcome uncertain: HTTP',e.code)
    except Exception as e:
        print('WhatsApp send outcome uncertain:',type(e).__name__)
    try: km_state.notification_result(path,owner,state,mid)
    except km_state.StateError as e: print('Notification outcome save failed; existing claim blocks resend:',str(e))
    print('Notification',sid,state)

if __name__ == '__main__':
    for sid,event,body in events(): send(sid,body,event)
