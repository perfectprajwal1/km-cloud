#!/usr/bin/env python3
"""One durable at-most-once aggregate WhatsApp notification per reel.
No automatic retry after an uncertain send. Claims/results stay in the repo.
"""
import json, os, pathlib, re, sys, urllib.request
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

def send(sid, body):
    token = os.environ.get('WA_TOKEN',''); phone = os.environ.get('WA_PHONE_ID',''); to = os.environ.get('WA_TO','')
    if not (token and phone and to):
        print('WA credentials missing; no claim or message created'); return
    try: path,owner = km_state.notification_claim(sid,body)
    except km_state.StateError as e:
        print('Notification suppressed:',str(e)); return
    payload = {'messaging_product':'whatsapp','to':to,'type':'text','text':{'body':body}}
    req = urllib.request.Request('https://graph.facebook.com/v21.0/'+phone+'/messages',
          data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    state='uncertain'; mid=''
    try:
        with urllib.request.urlopen(req,timeout=30) as r: obj=json.loads(r.read())
        mid=str(obj.get('messages',[{}])[0].get('id','')); state='sent' if mid else 'uncertain'
    except Exception as e:
        print('WhatsApp send outcome uncertain:',type(e).__name__)
    try: km_state.notification_result(path,owner,state,mid)
    except km_state.StateError as e: print('Notification outcome save failed; existing claim blocks resend:',str(e))
    print('Notification',sid,state)

if __name__ == '__main__':
    for sid,body in summaries(): send(sid,body)
