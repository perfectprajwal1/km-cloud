#!/usr/bin/env python3
"""Offline integration tests with real git bare remote. Never calls live APIs."""
import importlib.util, json, multiprocessing, os, pathlib, shutil, subprocess, sys, tempfile, time, unittest
SRC = pathlib.Path(__file__).resolve().parents[1]

def run(*args, cwd=None):
    p=subprocess.run(args,cwd=cwd,capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stderr)
    return p.stdout.strip()

def mod(root, name='km_state'):
    sys.path.insert(0,str(root/'scripts'))
    spec=importlib.util.spec_from_file_location(name,root/'scripts'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.modules[name]=module
    return module

def worker(root, sid, barrier, q, same=False):
    m=mod(pathlib.Path(root)); owner=root
    try:
        barrier.wait(10)
        m.write_receipt(sid,'youtube',{'state':'pending'},owner)
        # This append stands in for the remote createPost mutation. The test
        # requires one durable claim before reaching this line.
        with open(pathlib.Path(root).parent/'mock-posts.log','a') as f:f.write(sid+'\n')
        m.write_receipt(sid,'youtube',{'state':'accepted','post_id':'mock-'+sid},owner)
        q.put('accepted '+sid)
    except m.StateError as e:q.put('blocked '+sid+' '+str(e))

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='km-state-test-');self.base=pathlib.Path(self.tmp.name)
        self.remote=self.base/'remote.git';run('git','init','--bare','--initial-branch=main',str(self.remote))
        self.seed=self.base/'seed';run('git','clone',str(self.remote),str(self.seed))
        for root in (self.seed,):
            run('git','config','user.email','test@example.invalid',cwd=root);run('git','config','user.name','test',cwd=root)
        (self.seed/'scripts').mkdir();
        for n in ('km_state.py','km_publish.py','km_meta.py','km_notify.py'):shutil.copy2(SRC/'scripts'/n,self.seed/'scripts'/n)
        (self.seed/'out').mkdir();(self.seed/'out/done.txt').write_text('TRUMP\n')
        (self.seed/'produced.json').write_text('{"produced":{}}')
        (self.seed/'code.txt').write_text('original code\n')
        run('git','add','.',cwd=self.seed);run('git','commit','-m','seed',cwd=self.seed);run('git','push','origin','main',cwd=self.seed)
        self.a=self.clone('a');self.b=self.clone('b');self.s=mod(self.a)
    def tearDown(self):self.tmp.cleanup()
    def clone(self,name):
        root=self.base/name;run('git','clone',str(self.remote),str(root))
        run('git','config','user.email','test@example.invalid',cwd=root);run('git','config','user.name','test',cwd=root)
        return root
    def raw(self,path):return self.s.read_at(self.s.latest(),path)
    def fail_push(self,on=True):
        hook=self.remote/'hooks/pre-receive'
        if on:hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o755)
        elif hook.exists():hook.unlink()
    def test_overlapping_same_story_one_mutation(self):
        barrier=multiprocessing.Barrier(2);q=multiprocessing.Queue()
        ps=[multiprocessing.Process(target=worker,args=(str(r),'NEW',barrier,q)) for r in (self.a,self.b)]
        for p in ps:p.start()
        for p in ps:p.join(30);self.assertEqual(p.exitcode,0)
        messages=[q.get(timeout=2) for _ in ps];print('OVERLAP same:',messages)
        self.assertEqual((self.base/'mock-posts.log').read_text().splitlines(),['NEW'])
        self.assertEqual(json.loads(self.raw('out/buffer_receipts/NEW_youtube.json'))['state'],'accepted')
    def test_overlapping_distinct_stories_merge(self):
        barrier=multiprocessing.Barrier(2);q=multiprocessing.Queue()
        ps=[multiprocessing.Process(target=worker,args=(str(r),sid,barrier,q)) for r,sid in ((self.a,'A'),(self.b,'B'))]
        for p in ps:p.start()
        for p in ps:p.join(30);self.assertEqual(p.exitcode,0)
        messages=[q.get(timeout=2) for _ in ps];print('OVERLAP distinct:',messages)
        self.assertTrue(all(x.startswith('accepted') for x in messages))
        self.assertEqual(sorted((self.base/'mock-posts.log').read_text().splitlines()),['A','B'])
    def test_stale_checkout_done_union_and_dirty_code_not_committed(self):
        b=mod(self.b);b.mark_done('CANCER')
        (self.a/'code.txt').write_text('dirty renderer change\n')
        self.s.mark_done('NEW')
        self.assertEqual(set(self.raw('out/done.txt').decode().split()),{'TRUMP','CANCER','NEW'})
        self.assertEqual(self.raw('code.txt'),b'original code\n')
        self.s.refresh_done();self.assertIn('CANCER',(self.a/'out/done.txt').read_text())
    def test_accepted_receipt_immutable(self):
        self.s.write_receipt('TRUMP','youtube',{'state':'pending'},'owner')
        self.s.write_receipt('TRUMP','youtube',{'state':'accepted','post_id':'first'},'owner')
        with self.assertRaises(self.s.StateError):self.s.write_receipt('TRUMP','youtube',{'state':'pending'},'other')
        self.assertEqual(json.loads(self.raw('out/buffer_receipts/TRUMP_youtube.json'))['post_id'],'first')
    def test_failed_claim_causes_zero_submission(self):
        pub=mod(self.a,'km_publish');pub.PERSIST=True;pub.DRY=False;pub.RESULT=str(self.base/'results.txt');pub.ATTEMPTS={};pub.STATE_BLOCKED=False
        pub.sys.argv=['km_publish.py','NEW'];os.environ['BUFFER_API_KEY']='dummy-not-secret';os.environ['PLATFORMS']='youtube'
        pub.read_pack=lambda sid:{};pub.channels=lambda key:{'youtube':[{'id':'c'}]};pub.upload_media=lambda *a:'https://example.invalid/media.mp4';pub.post_query=lambda *a:'mock'
        calls=[];pub.gql=lambda *a:calls.append(a)
        self.fail_push()
        try:pub.main()
        finally:self.fail_push(False);os.environ.pop('BUFFER_API_KEY',None);os.environ.pop('PLATFORMS',None)
        self.assertEqual(calls,[]);self.assertTrue(pub.STATE_BLOCKED)
        self.assertIsNone(self.raw('out/buffer_receipts/NEW_youtube.json'))
    def test_accepted_response_save_failure_keeps_pending(self):
        self.s.write_receipt('NEW','youtube',{'state':'pending'},'owner');self.fail_push()
        try:
            with self.assertRaises(self.s.StateError):self.s.write_receipt('NEW','youtube',{'state':'accepted','post_id':'remote-created'},'owner')
        finally:self.fail_push(False)
        self.assertEqual(self.s.receipt('NEW','youtube')['state'],'pending')
        with self.assertRaises(self.s.StateError):self.s.write_receipt('NEW','youtube',{'state':'pending'},'retry')
    def test_notification_claim_at_most_once(self):
        self.s.notification_claim('NEW','one message')
        b=mod(self.b)
        with self.assertRaises(b.StateError):b.notification_claim('NEW','repeat message')
    def test_published_success_has_an_independent_notification_claim(self):
        self.s.notification_claim('NEW','early deferred note')
        b=mod(self.b)
        path,owner=b.notification_claim('NEW','published success',event='published')
        self.assertTrue(path.endswith('NEW_published.json'))
        with self.assertRaises(b.StateError):b.notification_claim('NEW','duplicate success',event='published')
    def test_definitely_rejected_notification_can_retry_but_uncertain_cannot(self):
        path,owner=self.s.notification_claim('NEW','uncertain event',event='uncertain')
        self.s.notification_result(path,owner,'uncertain')
        b=mod(self.b)
        with self.assertRaises(b.StateError):b.notification_claim('NEW','uncertain retry',event='uncertain')
        path,owner=self.s.notification_claim('NEW','published success',event='published')
        self.s.notification_result(path,owner,'failed')
        b.notification_claim('NEW','published success retry',event='published')
    def test_progress_merges_distinct_produced_and_preserves_remote_code(self):
        (self.a/'produced.json').write_text('{"produced":{"A":{"file":"a.txt"}}}')
        (self.b/'produced.json').write_text('{"produced":{"B":{"file":"b.txt"}}}')
        mod(self.b).progress();self.s.progress()
        self.assertEqual(set(json.loads(self.raw('produced.json'))['produced']),{'A','B'})
    def test_same_story_progress_conflict_stops_without_overwrite(self):
        (self.a/'inbox/NEW').mkdir(parents=True);(self.b/'inbox/NEW').mkdir(parents=True)
        (self.a/'inbox/NEW/pack.txt').write_text('A');(self.b/'inbox/NEW/pack.txt').write_text('B')
        mod(self.b).progress()
        with self.assertRaises(self.s.StateError):self.s.progress()
        self.assertEqual(self.raw('inbox/NEW/pack.txt'),b'B')
    def test_no_automatic_legacy_backfill(self):
        self.assertEqual(self.s.publish_candidates(),[])
        self.s.mark_done('NEW');self.assertEqual(self.s.publish_candidates(),['NEW'])
        for n in ('youtube','tiktok','linkedin'):
            self.s.write_receipt('NEW',n,{'state':'pending'},n)
        self.assertEqual(self.s.publish_candidates(),[])
    def test_lost_successful_push_acknowledgement(self):
        original=self.s.git;fired=[False]
        def wrapper(*args,**kwargs):
            p=original(*args,**kwargs)
            if args[0]=='push' and not fired[0]:
                fired[0]=True;p.returncode=1
            return p
        self.s.git=wrapper
        self.s.mark_done('NEW');self.assertIn('NEW',self.raw('out/done.txt').decode())
    def test_notification_aggregation(self):
        notify=mod(self.a,'km_notify');notify.RESULT=self.base/'results.txt'
        notify.RESULT.write_text('accepted NEW youtube id=1\nfailed NEW tiktok request uncertain\naccepted NEW instagram id=2\n')
        items=list(notify.summaries());self.assertEqual(len(items),1)
        self.assertIn('youtube, instagram',items[0][1]);self.assertIn('tiktok',items[0][1])

    def test_accepted_push_lost_ack_is_idempotent_and_keeps_media_url(self):
        self.s.write_receipt('NEW','youtube',{'state':'pending','media_url':'https://example.invalid/NEW.mp4'},'owner')
        original=self.s.git;fired=[False]
        def wrapper(*args,**kwargs):
            p=original(*args,**kwargs)
            if args[0]=='push' and not fired[0]:fired[0]=True;p.returncode=1
            return p
        self.s.git=wrapper
        self.s.write_receipt('NEW','youtube',{'state':'accepted','post_id':'first'},'owner')
        rec=self.s.receipt('NEW','youtube');self.assertEqual(rec['state'],'accepted');self.assertIn('media_url',rec)
    def test_unknown_receipt_blocks_new_owner(self):
        self.s.write_receipt('NEW','youtube',{'state':'pending','media_url':'https://example.invalid/NEW.mp4'},'owner')
        self.s.write_receipt('NEW','youtube',{'state':'unknown'},'owner')
        with self.assertRaises(self.s.StateError):self.s.write_receipt('NEW','youtube',{'state':'pending'},'retry')
    def test_buffer_lost_response_persists_unknown_and_never_repeats(self):
        pub=mod(self.a,'km_publish');pub.PERSIST=True;pub.DRY=False;pub.RESULT=str(self.base/'results.txt');pub.ATTEMPTS={};pub.STATE_BLOCKED=False
        pub.sys.argv=['km_publish.py','NEW'];os.environ['BUFFER_API_KEY']='dummy-not-secret';os.environ['PLATFORMS']='youtube'
        pub.read_pack=lambda sid:{};pub.channels=lambda key:{'youtube':[{'id':'c'}]};pub.upload_media=lambda *a:'https://example.invalid/media.mp4';pub.post_query=lambda *a:'mock'
        calls=[]
        def lost(*a):calls.append(a);raise pub.Soft('mock response lost')
        pub.gql=lost
        try:pub.main();pub.main()
        finally:os.environ.pop('BUFFER_API_KEY',None);os.environ.pop('PLATFORMS',None)
        self.assertEqual(len(calls),1);self.assertEqual(self.s.receipt('NEW','youtube')['state'],'unknown')

    def test_meta_failed_claim_sends_no_create_request(self):
        pub=mod(self.a,'km_publish');meta=mod(self.a,'km_meta');pub.PERSIST=True;pub.ATTEMPTS={};pub.STATE_BLOCKED=False
        calls=[];meta.request=lambda *a,**kw:calls.append((a,kw))
        self.fail_push()
        try:
            with self.assertRaises(pub.Soft):meta.submit(pub,'NEW','instagram','dummy','account','caption','https://example.invalid/NEW.mp4')
        finally:self.fail_push(False)
        self.assertEqual(calls,[])
    def test_notification_network_lost_response_no_retry(self):
        notify=mod(self.a,'km_notify');notify.km_state=self.s;calls=[]
        def lost(*a,**kw):calls.append(1);raise TimeoutError('mock')
        notify.urllib.request.urlopen=lost
        for key in ('WA_TOKEN','WA_PHONE_ID','WA_TO'):os.environ[key]='mock'
        try:notify.send('NEW','one summary');notify.send('NEW','again')
        finally:
            for key in ('WA_TOKEN','WA_PHONE_ID','WA_TO'):os.environ.pop(key,None)
        self.assertEqual(len(calls),1)
        self.assertEqual(json.loads(self.raw('out/notifications/NEW.json'))['state'],'uncertain')
    def test_rejected_submission_keeps_deterministic_identifiers(self):
        self.s.write_receipt('NEW','youtube',{'state':'pending','channel_id':'c','media_url':'https://example.invalid/NEW.mp4'},'owner')
        self.s.write_receipt('NEW','youtube',{'state':'rejected','reason':'definite refusal'},'owner')
        rec=self.s.receipt('NEW','youtube');self.assertEqual(rec['state'],'rejected');self.assertEqual(rec['channel_id'],'c')

class LauncherTests(unittest.TestCase):
    def test_explicit_done_story_skips_render(self):
        for name in ('make_reel','resume_failed'):
            spec=importlib.util.spec_from_file_location(name,SRC/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            with tempfile.TemporaryDirectory() as tmp:
                m.ROOT=pathlib.Path(tmp);(m.ROOT/'out').mkdir();(m.ROOT/'out/done.txt').write_text('TRUMP\n')
                old=sys.argv;sys.argv=[name+'.py','TRUMP']
                m.run=lambda *a: self.fail('done story must not start converter/voice/render')
                try:self.assertEqual(m.main(),0)
                finally:sys.argv=old
    def test_exact_script_voice_restoration_offline(self):
        import hashlib
        sys.path.insert(0,str(SRC))
        from scripts.gemini_voice import MODEL,VOICE
        spec=importlib.util.spec_from_file_location('launcher',SRC/'make_reel.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as tmp:
            m.ROOT=pathlib.Path(tmp);(m.ROOT/'stories').mkdir()
            story={'id':'NEW','cards':[{'vo':'Known text','voice_tone':'neutral'}]}
            (m.ROOT/'stories/NEW.json').write_text(json.dumps(story))
            fp=hashlib.sha256(json.dumps([['Known text'],['neutral'],MODEL,VOICE,'two_halves_v1'],ensure_ascii=False).encode()).hexdigest()[:20]
            work=m.ROOT/'one_call_voice'/fp;(work/'cards').mkdir(parents=True)
            audio=b'offline cached bytes';(work/'cards/c01.wav').write_bytes(audio)
            (work/'installed_reviewed.json').write_text(json.dumps([{'name':'c01.wav','sha256':hashlib.sha256(audio).hexdigest()}]))
            m.restore_cached_voice('NEW');self.assertEqual((m.ROOT/'public/voice_in/c01.wav').read_bytes(),audio)
            (work/'cards/c01.wav').write_bytes(b'corrupt')
            # Receipt uncertainty is a note; gemini_voice can resplit the
            # durable master audio instead of stopping an approved build.
            m.restore_cached_voice('NEW')

    def test_workflow_fresh_checkout_and_shared_group(self):
        import yaml
        for name in ('km_reel.yml','km_publish.yml'):
            obj=yaml.safe_load((SRC/'.github/workflows'/name).read_text())
            self.assertEqual(obj['concurrency']['group'],'km-reel');self.assertFalse(obj['concurrency']['cancel-in-progress'])
            job=next(iter(obj['jobs'].values()));steps=job['steps']
            checkout=next(x for x in steps if x.get('uses','').startswith('actions/checkout'))
            self.assertEqual(checkout['with']['ref'],'main')
            self.assertTrue(any('git checkout -B main origin/main' in x.get('run','') for x in steps))
        test=(SRC/'.github/workflows/buffer_test.yml').read_text();self.assertNotIn('buffer_test.py',test)

if __name__ == '__main__':unittest.main(verbosity=2)
