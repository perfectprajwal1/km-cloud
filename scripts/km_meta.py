"""Direct Meta publishing. No secrets in receipts/logs. Each network fails independently.
Live Meta effects require META_ENABLE=true. Dry-run only makes identity GET requests.
Facebook exchange/derivation occurs only on live runs, after account review.
"""
import json, os, time, urllib.request, urllib.parse, urllib.error
from urllib.parse import urlparse

VERSION = os.environ.get('META_API_VERSION', 'v25.0')
FB = 'https://graph.facebook.com/' + VERSION
IG = 'https://graph.instagram.com/' + VERSION
TH = 'https://graph.threads.com/v1.0'
FB_APP_ID = os.environ.get('FB_APP_ID', '2213813046222236')
FB_PAGE_ID = os.environ.get('FB_PAGE_ID', '1404139492777541')
IG_ID = os.environ.get('IG_ACCOUNT_ID', '17841423978484959')
NETWORKS = ('facebook', 'instagram', 'threads')
SECRETS = []

class MetaError(Exception):
    pass

def clean(value):
    text = str(value)
    for secret in SECRETS:
        if secret:
            text = text.replace(secret, '***')
    return text

def request(url, token='', data=None, params=None, headers=None):
    """Never log request URLs, bodies, tokens, or raw exceptions containing them."""
    if params:
        url += '?' + urllib.parse.urlencode(params)
    h = {'Authorization': 'Bearer ' + token} if token else {}
    h.update(headers or {})
    body = None if data is None else urllib.parse.urlencode(data).encode()
    if body is not None:
        h.setdefault('Content-Type', 'application/x-www-form-urlencoded')
    req = urllib.request.Request(url, data=body, headers=h, method='GET' if data is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            response = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Token-free code only: Meta error bodies can echo sensitive parameters.
        raise MetaError('Meta HTTP ' + str(e.code)) from None
    except Exception as e:
        raise MetaError('Meta request uncertain: ' + type(e).__name__) from None
    if response.get('error'):
        raise MetaError('Meta API code ' + str(response['error'].get('code', 'unknown')))
    return response


def identity(network):
    token = (os.environ.get('FB_PAGE_TOKEN') or os.environ.get('FB_USER_TOKEN', '')) if network == 'facebook' else os.environ.get({'instagram':'IG_TOKEN','threads':'THREADS_TOKEN'}[network], '')
    token = token.strip()
    if not token:
        raise MetaError('missing credential for ' + network)
    SECRETS.append(token)
    if network == 'instagram':
        account = request(IG + '/me', token, params={'fields':'user_id,username'})
        if isinstance(account.get('data'), list) and len(account['data']) == 1:
            account = account['data'][0]
        aid = str(account.get('user_id') or account.get('id') or '')
        if aid != IG_ID:
            raise MetaError('Instagram token identity does not match configured IG_ACCOUNT_ID; inspect dry-run identity')
        return token, aid, account.get('username', '')
    if network == 'threads':
        account = request(TH + '/me', token, params={'fields':'id,username'})
        expected = os.environ.get('THREADS_USERNAME', 'khabarminutenepal').strip().lstrip('@')
        if not expected:
            raise MetaError('THREADS_USERNAME not configured; verify intended profile before live use')
        if str(account.get('username', '')).lower() != expected.lower():
            raise MetaError('Threads token belongs to a different username')
        return token, str(account['id']), account['username']
    if os.environ.get('FB_PAGE_TOKEN'):
        page = request(FB + '/me', token, params={'fields':'id,name'})
        if str(page.get('id')) != FB_PAGE_ID:
            raise MetaError('FB_PAGE_TOKEN belongs to a different Page')
        return token, FB_PAGE_ID, page.get('name', '')
    # Dry-run never prints Page tokens from the response and never exchanges tokens.
    pages = request(FB + '/me/accounts', token, params={'fields':'id,name,tasks'})
    page = next((p for p in pages.get('data', []) if str(p.get('id')) == FB_PAGE_ID), None)
    if not page:
        raise MetaError('configured Facebook Page not in first returned account page; resolve access/pagination')
    if not set(page.get('tasks', [])).intersection({'CREATE_CONTENT','MANAGE','PROFILE_PLUS_CREATE_CONTENT','PROFILE_PLUS_FULL_CONTROL'}):
        raise MetaError('Facebook Page token lacks a verified create-content task')
    return token, FB_PAGE_ID, page.get('name', '')


def page_token(user):
    if os.environ.get('FB_PAGE_TOKEN'):
        return os.environ['FB_PAGE_TOKEN'].strip()
    secret = os.environ.get('FB_APP_SECRET', '').strip()
    if not secret:
        raise MetaError('FB_APP_SECRET missing')
    SECRETS.append(secret)
    long = request(FB + '/oauth/access_token', params={
        'grant_type':'fb_exchange_token', 'client_id':FB_APP_ID,
        'client_secret':secret, 'fb_exchange_token':user})['access_token']
    SECRETS.append(long)
    # Never save this JSON: it contains all Page tokens.
    pages = request(FB + '/me/accounts', long, params={'fields':'id,name,access_token,tasks'})
    page = next((p for p in pages.get('data', []) if str(p.get('id')) == FB_PAGE_ID), None)
    if not page or not page.get('access_token'):
        raise MetaError('long-lived Page token not returned for configured Page')
    token = page['access_token']; SECRETS.append(token)
    return token


def caption(pub, pack, network):
    copy = dict(pack)
    copy['tiktok_caption'] = pack.get({'facebook':'facebook_post','instagram':'instagram_caption','threads':'threads_post'}[network]) or pack.get('tiktok_caption')
    text = pub.build_caption(copy)
    if network == 'threads' and len(text.encode('utf-8')) > 500:
        # Fail instead of chopping Nepali text or hashtags into malformed fragments.
        raise MetaError('Threads caption exceeds conservative 500-byte limit; review a shorter caption')
    return text


def wait_container(host, cid, token, field):
    for attempt in range(5):
        state = request(host + '/' + cid, token, params={'fields':field})
        status = state.get(field)
        if status == 'FINISHED':
            return
        if status in ('ERROR','EXPIRED','PUBLISHED'):
            raise MetaError('container status ' + str(status) + '; inspect before retry')
        if attempt < 4:
            time.sleep(60)
    raise MetaError('container still processing after bounded checks; receipt blocks duplicate submission')


def submit(pub, sid, network, token, aid, text, url):
    # This durable checkpoint blocks repeat sends after any lost response.
    pub.save_receipt(sid, network, state='pending', channel_id=aid, media_url=url, stage='before_create')
    if network == 'facebook':
        token = page_token(token)
        start = request(FB + '/' + aid + '/video_reels', token, data={'upload_phase':'start'})
        vid = str(start['video_id']); upload = start['upload_url']
        # Never send Page credentials to an unexpected upload host.
        if urlparse(upload).scheme != 'https' or urlparse(upload).hostname != 'rupload.facebook.com':
            raise MetaError('unrecognized Facebook upload host')
        pub.save_receipt(sid, network, state='pending', channel_id=aid, container_id=vid, stage='upload')
        res = request(upload, data={}, headers={'Authorization':'OAuth ' + token, 'file_url':url})
        if res.get('success') is not True:
            raise MetaError('Facebook hosted upload not confirmed')
        res = request(FB + '/' + aid + '/video_reels', token, data={'upload_phase':'finish','video_id':vid,'video_state':'PUBLISHED','description':text})
        if res.get('success') is not True:
            raise MetaError('Facebook publish request not confirmed')
        pub.save_receipt(sid, network, state='accepted', channel_id=aid, post_id=vid, status='publish_requested')
        # Read processing status, do not call acceptance final delivery.
        status = request(FB + '/' + vid, token, params={'fields':'status'}).get('status', {})
        if status.get('publishing_phase', {}).get('status') == 'complete':
            return vid, 'publishing_complete'
        return vid, 'publish_requested_processing_unverified'
    host = IG if network == 'instagram' else TH
    edge = '/media' if network == 'instagram' else '/threads'
    data = {'media_type':'REELS' if network == 'instagram' else 'VIDEO','video_url':url}
    data['caption' if network == 'instagram' else 'text'] = text
    if network == 'instagram':
        data['share_to_feed'] = 'true'
    cid = str(request(host + '/' + aid + edge, token, data=data)['id'])
    pub.save_receipt(sid, network, state='pending', channel_id=aid, container_id=cid, stage='processing')
    wait_container(host, cid, token, 'status_code' if network == 'instagram' else 'status')
    pub.save_receipt(sid, network, state='pending', channel_id=aid, container_id=cid, stage='before_publish')
    pid = str(request(host + '/' + aid + ('/media_publish' if network == 'instagram' else '/threads_publish'), token, data={'creation_id':cid})['id'])
    pub.save_receipt(sid, network, state='accepted', channel_id=aid, container_id=cid, post_id=pid, status='publish_returned_id')
    return pid, 'publish_returned_id'


def run(pub):
    if len(pub.sys.argv) != 2:
        return
    sid = pub.sys.argv[1]
    if not pub.re.fullmatch(r'[A-Za-z0-9_-]+', sid):
        return
    selected_raw = os.environ.get('PLATFORMS', '').strip()
    selected = [n.strip().lower() for n in selected_raw.split(',') if n.strip()] if selected_raw else list(NETWORKS)
    selected = [n for n in dict.fromkeys(selected) if n in NETWORKS]
    if sid in pub.TIKTOK_BLOCKED and not selected_raw:
        return
    if not pub.DRY and os.environ.get('META_ENABLE', 'false').lower() != 'true':
        if selected_raw:
            for network in selected:
                pub.result('failed', sid, network + ' live Meta posting disabled until recipients/text approved')
        return
    for network in selected:
        has_token = (os.environ.get('FB_PAGE_TOKEN') or os.environ.get('FB_USER_TOKEN')) if network == 'facebook' else os.environ.get({'instagram':'IG_TOKEN','threads':'THREADS_TOKEN'}[network])
        if not has_token:
            if selected_raw:
                pub.result('failed', sid, network + ' token missing')
            continue
        try:
            token, aid, name = identity(network)
            pack = pub.read_pack(sid); text = caption(pub, pack, network)
            if pub.DRY:
                print('DRY_RUN Meta destination:', network, aid, name)
                print('DRY_RUN Meta caption:', text)
                print('DRY_RUN Meta receipt:', pub.load_receipt(sid, network))
                pub.result('dry_run', sid, network + ' identity and caption checked; no mutation')
                continue
            old = pub.load_receipt(sid, network)
            if old.get('state') == 'accepted':
                pub.result('skipped', sid, network + ' already accepted'); continue
            if old.get('state') == 'pending':
                raise MetaError('previous submission uncertain; inspect recorded container/post, do not retry blindly')
            url = pub.upload_media(sid, os.environ.get('GH_PAT', ''))
            pid, status = submit(pub, sid, network, token, aid, text, url)
            pub.result('accepted', sid, network + ' Meta id=' + pid + ' status=' + status)
        except Exception as e:
            pub.result('failed', sid, network + ' ' + clean(e))
