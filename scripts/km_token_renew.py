#!/usr/bin/env python3
"""Refresh IG/Threads tokens and sealed-box-save repository secrets. No posting.
No secret files/artifacts, request URLs or raw API responses are logged.
Preflight only is default. FB bootstrap requires explicit manual opt-in.
"""
import base64, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
from nacl.public import PublicKey, SealedBox
from nacl.encoding import Base64Encoder

REPO = os.environ.get('GITHUB_REPOSITORY', 'perfectprajwal1/km-cloud')
PREFLIGHT = os.environ.get('PREFLIGHT_ONLY', 'true').lower() == 'true'
BOOTSTRAP_FB = os.environ.get('BOOTSTRAP_FB_PAGE', 'false').lower() == 'true'
WRITER = os.environ.get('META_SECRETS_PAT', '').strip()
GITHUB_API = 'https://api.github.com/repos/' + REPO
ALLOWED = {'IG_TOKEN','THREADS_TOKEN','FB_PAGE_TOKEN'}

class SafeError(Exception):
    pass

def http(url, method='GET', token='', params=None, body=None, headers=None):
    if params:
        url += '?' + urllib.parse.urlencode(params)
    h = dict(headers or {})
    if token:
        h['Authorization'] = 'Bearer ' + token
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=payload, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
            data = json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as e:
        # Raw Meta/GitHub responses and URLs can reveal tokens; do not print them.
        raise SafeError('HTTP ' + str(e.code)) from None
    except Exception as e:
        raise SafeError('request uncertain: ' + type(e).__name__) from None
    if data.get('error'):
        raise SafeError('API error code ' + str(data['error'].get('code', 'unknown')))
    return data


def gh(method, suffix, body=None):
    return http(GITHUB_API + suffix, method, WRITER, body=body, headers={
        'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})


def public_key():
    if REPO != 'perfectprajwal1/km-cloud':
        raise SafeError('repository identity mismatch')
    if not WRITER:
        raise SafeError('META_SECRETS_PAT missing')
    key = gh('GET', '/actions/secrets/public-key')
    if not key.get('key_id') or not key.get('key'):
        raise SafeError('GitHub public key not returned')
    return key


def save_secret(name, value, key):
    if name not in ALLOWED or not value:
        raise SafeError('invalid target secret')
    encrypted = SealedBox(PublicKey(key['key'].encode(), encoder=Base64Encoder)).encrypt(value.encode())
    data = {'encrypted_value':base64.b64encode(encrypted).decode(), 'key_id':key['key_id']}
    for attempt in range(3):
        try:
            gh('PUT', '/actions/secrets/' + name, data)
            return
        except SafeError:
            if attempt == 2:
                raise SafeError('GitHub secret save not confirmed after 3 tries; inspect run before retry') from None
            time.sleep(5)


def identity(network, token):
    if network == 'instagram':
        r = http('https://graph.instagram.com/v25.0/me', token=token, params={'fields':'user_id,username'})
        if isinstance(r.get('data'), list) and len(r['data']) == 1:
            r = r['data'][0]
        if str(r.get('user_id') or r.get('id')) != '17841423978484959':
            raise SafeError('Instagram account ID mismatch')
    else:
        r = http('https://graph.threads.com/v1.0/me', token=token, params={'fields':'id,username'})
        if str(r.get('id')) != '28702519189375738' or str(r.get('username','')).lower() != 'khabarminutenepal':
            raise SafeError('Threads ID/username mismatch')
    return r


def renew(network, key):
    name = 'IG_TOKEN' if network == 'instagram' else 'THREADS_TOKEN'
    token = os.environ.get(name, '').strip()
    if not token:
        raise SafeError(name + ' missing')
    identity(network, token)
    if PREFLIGHT:
        return 'identity passed; no refresh/save; write permission not proven'
    host = 'https://graph.instagram.com' if network == 'instagram' else 'https://graph.threads.com'
    grant = 'ig_refresh_token' if network == 'instagram' else 'th_refresh_token'
    # Call once. Do not re-refresh just because saving encounters an error.
    r = http(host + '/refresh_access_token', params={'grant_type':grant,'access_token':token})
    new = r.get('access_token','')
    try:
        expires = int(r.get('expires_in',0))
    except (ValueError,TypeError):
        raise SafeError('refresh expiry malformed') from None
    if not new or expires <= 0:
        raise SafeError('refresh did not return a token and expiry')
    identity(network, new)
    save_secret(name, new, key)
    return 'refreshed and repository secret saved; expires_in=' + str(expires) + 's'


def bootstrap_facebook(key):
    """One-time save, not periodic FB token renewal. Reuse verified v3.1 helpers."""
    import km_meta
    # This imported helper requires v3.1 or newer with direct Page lookup/diagnostics.
    existing = os.environ.get('FB_PAGE_TOKEN','').strip()
    if existing:
        km_meta.identity('facebook')
        return 'existing FB_PAGE_TOKEN identity passed; no overwrite'
    user = os.environ.get('FB_USER_TOKEN','').strip()
    if not user:
        raise SafeError('FB_USER_TOKEN seed missing')
    km_meta.facebook_diagnostics(user)
    km_meta.identity('facebook')
    if PREFLIGHT:
        return 'bootstrap identity/scopes passed; no exchange/save'
    page = km_meta.page_token(user)
    save_secret('FB_PAGE_TOKEN', page, key)
    return 'long-lived Page token derived and repository secret saved'


def notice(lines):
    token = os.environ.get('WA_TOKEN','').strip()
    pid = os.environ.get('WA_PHONE_ID','').strip()
    to = os.environ.get('WA_TO','').strip()
    if not token or not pid or not to:
        print('WhatsApp notice skipped: WA credentials missing')
        return False
    if not pid.isdigit():
        print('WhatsApp notice skipped: invalid sender identifier')
        return False
    text = ('KM token preflight' if PREFLIGHT else 'KM token renewal') + '\n' + '\n'.join(lines)
    try:
        r = http('https://graph.facebook.com/v25.0/' + pid + '/messages', 'POST', token,
            body={'messaging_product':'whatsapp','to':to,'type':'text','text':{'body':text}})
        if not r.get('messages'):
            raise SafeError('message acceptance not returned')
        print('WhatsApp notice accepted by API, delivery unverified')
        return True
    except Exception:
        print('WhatsApp notice not confirmed; inspect the workflow result')
        return False


def main():
    lines, failed = [], False
    try:
        key = public_key()
        print('GitHub repository public key accessible; preflight alone cannot prove Secrets write')
    except Exception as e:
        # Exception messages from our own code are safe. Unknown third-party errors reduced to type.
        detail = str(e) if isinstance(e,SafeError) else type(e).__name__
        lines.append('FAIL: GitHub secret access (' + detail + ')')
        print(lines[-1])
        if not PREFLIGHT:
            notice(lines)
        return 1
    for network in ('instagram','threads'):
        try:
            lines.append('OK: ' + network + ' ' + renew(network,key))
        except Exception as e:
            detail = str(e) if isinstance(e,SafeError) else type(e).__name__
            lines.append('FAIL: ' + network + ' (' + detail + '). Token may need reauthorization; check expiry/age and save access.')
            failed = True
    if BOOTSTRAP_FB:
        try:
            lines.append('OK: facebook ' + bootstrap_facebook(key))
        except Exception as e:
            detail = str(e) if isinstance(e,SafeError) else type(e).__name__
            lines.append('FAIL: facebook bootstrap (' + detail + ')')
            failed = True
    for line in lines:
        print(line)
    # WhatsApp business text requires an open conversation window; failures remain visible in Actions.
    delivered = True if PREFLIGHT else notice(lines)
    return 1 if failed or not delivered else 0

if __name__ == '__main__':
    sys.exit(main())
