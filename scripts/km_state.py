#!/usr/bin/env python3
"""Durable state transactions. No reset, stash, rebase, force push or broad add.
Git commits are built with a temporary index on latest main. Remote CAS retries
merge distinct paths; same-path ambiguity stops. API mutations need a claim first.
"""
import contextlib, fcntl, json, os, pathlib, re, subprocess, tempfile, time, uuid

class StateError(Exception):
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRANCH = 'main'

def git(*args, input=None, env=None, check=True):
    p = subprocess.run(['git', *args], cwd=ROOT, input=input, capture_output=True,
                       env={**os.environ, **(env or {})}, timeout=180)
    if check and p.returncode:
        # Do not echo git stderr: credential helpers/URLs can contain secrets.
        raise StateError('state git ' + args[0] + ' failed (code ' + str(p.returncode) + '); see state artifact')
    return p

@contextlib.contextmanager
def lock():
    path = git('rev-parse', '--git-path', 'km-state.lock').stdout.decode().strip()
    with open(ROOT / path, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield

def latest():
    git('fetch', '--quiet', 'origin', 'refs/heads/main:refs/remotes/origin/main')
    return git('rev-parse', 'refs/remotes/origin/main').stdout.decode().strip()

def read_at(rev, path):
    p = git('show', rev + ':' + path, check=False)
    if not p.returncode:
        return p.stdout
    # A missing file is allowed, other repository failures are not.
    exists = git('ls-tree', rev, '--', path).stdout
    if exists:
        raise StateError('cannot read existing state ' + path)
    return None

def current(path):
    with lock():
        return read_at(latest(), path)

def encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()

def decode(raw, default=None):
    return json.loads(raw) if raw is not None else default

def transaction(builder, message):
    """builder(latest_sha) returns exact files. Recompute on each rejected push.
    A successful push with lost acknowledgement is recognized on the next read.
    """
    with lock():
        for attempt in range(5):
            head = latest()
            changes = builder(head)
            changes = {p:b for p,b in changes.items() if b != read_at(head, p)}
            if not changes:
                return
            fd, idx = tempfile.mkstemp(prefix='km-index-'); os.close(fd); os.unlink(idx)
            env = {'GIT_INDEX_FILE':idx}
            try:
                git('read-tree', head, env=env)
                for path, raw in changes.items():
                    if raw is None:
                        git('update-index', '--force-remove', '--', path, env=env)
                    else:
                        blob = git('hash-object', '-w', '--stdin', input=raw).stdout.decode().strip()
                        git('update-index', '--add', '--cacheinfo', '100644', blob, path, env=env)
                tree = git('write-tree', env=env).stdout.decode().strip()
                commit = git('commit-tree', tree, '-p', head, input=(message+'\n').encode()).stdout.decode().strip()
                pushed = git('push', '--quiet', 'origin', commit+':refs/heads/main', check=False)
                if pushed.returncode == 0:
                    return
                print('STATE push rejected/uncertain; fetching and merging attempt', attempt+1, flush=True)
            finally:
                if os.path.exists(idx): os.unlink(idx)
            time.sleep(min(attempt+1, 3))
        # Final read distinguishes a lost success acknowledgement from failure.
        head = latest()
        if all(raw == read_at(head,p) for p,raw in builder(head).items()):
            return
        raise StateError('state push exhausted; no new external submission permitted')

def receipt(sid, network):
    path = 'out/buffer_receipts/'+sid+'_'+network+'.json'
    raw = current(path)
    if raw is not None:
        obj = decode(raw)
        if obj.get('state') not in ('pending','unknown','accepted','rejected'):
            raise StateError('unrecognized receipt state; manual inspection required')
        return obj
    if network == 'tiktok':
        raw = current('out/buffer_posted.txt')
        if raw and sid in raw.decode().split(): return {'state':'accepted','legacy':True}
    return {}

def write_receipt(sid, network, data, owner):
    path = 'out/buffer_receipts/'+sid+'_'+network+'.json'
    data = dict(data, story_id=sid, platform=network, attempt_id=owner)
    def build(head):
        old = decode(read_at(head,path), {})
        merged = dict(old, **data)
        if old == merged: return {}
        if old.get('state') == 'accepted':
            raise StateError('already accepted; existing receipt preserved')
        if old.get('state') in ('pending','unknown') and old.get('attempt_id') != owner:
            raise StateError('another/uncertain attempt owns receipt; no retry')
        return {path:encoded(merged)}
    transaction(build, 'KM receipt '+sid+' '+network)
    local = ROOT / path; local.parent.mkdir(parents=True,exist_ok=True); local.write_bytes(encoded(data))

def mark_done(sid):
    path = 'out/done/'+sid+'.json'
    data = dict(story_id=sid, drive_name=sid+'.mp4', workflow_run_id=os.environ.get('GITHUB_RUN_ID',''),
                publisher_version='5.8', publish_pending=True)
    def build(head):
        old = read_at(head,path)
        done = set((read_at(head,'out/done.txt') or b'').decode().split())
        done.add(sid)
        return {path:old if old is not None else encoded(data),
                'out/done.txt': ('\n'.join(sorted(done))+'\n').encode()}
    transaction(build, 'KM Drive done '+sid)

def progress():
    """Only generated resume data. Same-path changes on remote require equality
    or a clean three-way merge. produced.json is a union keyed by story id.
    """
    base = git('rev-parse','HEAD').stdout.decode().strip()
    candidates = set(git('ls-files','--','one_call_voice','stories','inbox','produced.json').stdout.decode().splitlines())
    for root in ('one_call_voice','stories','inbox'):
        p = ROOT/root
        if p.exists(): candidates.update(str(f.relative_to(ROOT)) for f in p.rglob('*') if f.is_file())
    snapshot = {p:(ROOT/p).read_bytes() if (ROOT/p).is_file() else None for p in candidates}
    snapshot = {p:b for p,b in snapshot.items() if b != read_at(base,p)}
    def build(head):
        out = {}
        for path, local in snapshot.items():
            remote = read_at(head,path); original = read_at(base,path)
            if path == 'produced.json' and local is not None:
                merged = decode(remote, {'produced':{}})
                for sid,val in decode(local, {'produced':{}})['produced'].items():
                    if sid in merged['produced'] and merged['produced'][sid] != val:
                        if val != decode(original, {'produced':{}})['produced'].get(sid):
                            raise StateError('produced same-story conflict '+sid)
                    else: merged['produced'][sid] = val
                out[path] = encoded(merged)
            elif remote == original or remote == local:
                out[path] = local
            else:
                raise StateError('resume same-path conflict '+path+'; artifacts retained')
        return out
    transaction(build, 'KM resume state')
    try: selection_history()
    except Exception as e: print('NOTE: variety history not saved (' + str(e)[:150] + '); reels are unaffected.', flush=True)

HISTORY = 'out/selection/history.json'

def selection_history():
    """Save variety history (written only after a successful render). Soft: caller ignores failures.
    Merge with remote: reels unioned by (id, content_hash), counts = remote + local gain."""
    local = ROOT / HISTORY
    if not local.is_file(): return
    mine = json.loads(local.read_text(encoding='utf-8'))
    if not isinstance(mine.get('reels'), list) or not isinstance(mine.get('seen'), dict) or not isinstance(mine.get('used_total'), dict):
        raise StateError('history file malformed; not saved')
    def build(head):
        remote = decode(read_at(head, HISTORY), {'version':mine.get('version','1.0'),'reels':[],'seen':{},'used_total':{}})
        have = {(r['id'], r['content_hash']) for r in remote['reels']}
        merged = dict(remote); merged['reels'] = list(remote['reels']); merged['seen'] = dict(remote['seen']); merged['used_total'] = dict(remote['used_total'])
        for r in mine['reels']:
            if (r['id'], r['content_hash']) not in have: merged['reels'].append(r)
        for k, v in mine['seen'].items(): merged['seen'].setdefault(k, v)
        # counts: add only for reels that were new to remote
        for r in mine['reels']:
            if (r['id'], r['content_hash']) in have: continue
            for k in r['selected']: merged['used_total'][k] = merged['used_total'].get(k, 0) + 1
        merged['reels'] = sorted(merged['reels'], key=lambda r: r.get('rendered_at', 0))[-20:]
        return {HISTORY: encoded(merged)}
    transaction(build, 'KM variety history')

def notification_claim(sid, body, event='summary'):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', sid) or not re.fullmatch(r'[a-z0-9_-]+', event):
        raise StateError('invalid notification identity')
    # Keep the original summary claim path for compatibility. Each later event
    # gets its own durable idempotency key, so an early deferred note cannot
    # consume the eventual published-success notice.
    path = 'out/notifications/'+sid+('.json' if event == 'summary' else '_'+event+'.json')
    owner = str(uuid.uuid4())
    def build(head):
        old = decode(read_at(head,path), {})
        if old and old.get('state') != 'failed' and old.get('attempt_id') != owner:
            raise StateError('notification already claimed; suppressed')
        return {path:encoded(dict(story_id=sid,state='claimed',attempt_id=owner,body=body))}
    transaction(build, 'KM one notification '+sid)
    return path, owner

def notification_result(path, owner, state, message_id=''):
    def build(head):
        old = decode(read_at(head,path), {})
        if old.get('attempt_id') != owner: raise StateError('notification owner mismatch')
        old.update(state=state, message_id=message_id)
        return {path:encoded(old)}
    transaction(build, 'KM notification outcome')

def refresh_done():
    raw = current('out/done.txt') or b''
    (ROOT/'out').mkdir(exist_ok=True)
    (ROOT/'out/done.txt').write_bytes(raw)

def publish_candidates():
    # Only enroll files produced by this version. Do not auto-publish historical
    # PC/legacy Drive reels lacking social receipts.
    head = latest()
    names = git('ls-tree','-r','--name-only',head,'--','out/done').stdout.decode().splitlines()
    ids = []
    for p in names:
        obj = decode(read_at(head,p), {})
        sid = obj.get('story_id','')
        if obj.get('publisher_version') not in ('5.7','5.8') or not re.fullmatch(r'[A-Za-z0-9_-]+',sid): continue
        enabled = ('tiktok','youtube','linkedin') + (('facebook','instagram','threads') if os.environ.get('META_ENABLE','false').lower() == 'true' else ())
        if any(decode(read_at(head,'out/buffer_receipts/'+sid+'_'+n+'.json'),{}).get('state') not in ('accepted','pending','unknown') for n in enabled):
            ids.append(sid)
    return sorted(ids)[:5]

def published_candidates():
    """Return proven fully accepted reels needing a success WhatsApp event.

    New 5.8 reels are eligible. For the one legacy gap this also backfills a
    reel whose old at-most-once message explicitly said posting was deferred.
    All currently enabled platform receipts must be accepted before a success
    message is claimed.
    """
    head = latest()
    names = git('ls-tree','-r','--name-only',head,'--','out/done').stdout.decode().splitlines()
    enabled = ('tiktok','youtube','linkedin')
    if os.environ.get('META_ENABLE','false').lower() == 'true':
        enabled += ('facebook','instagram','threads')
    ids = []
    for done_path in names:
        obj = decode(read_at(head,done_path), {})
        sid = obj.get('story_id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',sid):
            continue
        is_current = obj.get('publisher_version') == '5.8'
        if not is_current:
            old_notice = decode(read_at(head,'out/notifications/'+sid+'.json'), {})
            body = str(old_notice.get('body',''))
            is_legacy_gap = old_notice.get('state') == 'sent' and 'Posting deferred or reel incomplete.' in body
            if not is_legacy_gap:
                continue
        notice = decode(read_at(head,'out/notifications/'+sid+'_published.json'),{})
        if notice and notice.get('state') != 'failed': continue
        if all(decode(read_at(head,'out/buffer_receipts/'+sid+'_'+network+'.json'),{}).get('state') == 'accepted' for network in enabled):
            ids.append(sid)
    return sorted(ids)

if __name__ == '__main__':
    import sys
    try:
        op = sys.argv[1]
        if op == 'progress': progress()
        elif op == 'refresh-done': refresh_done()
        elif op == 'selection-history': selection_history()
        elif op == 'done':
            for sid in sys.argv[2:]:
                if not re.fullmatch(r'[A-Za-z0-9_-]+',sid): raise StateError('bad story ID')
                mark_done(sid)
        elif op == 'candidates': print('\n'.join(publish_candidates()))
        elif op == 'published-candidates': print('\n'.join(published_candidates()))
        else: raise StateError('unknown command')
    except Exception as e:
        print('STATE STOP:', str(e)); sys.exit(1)
