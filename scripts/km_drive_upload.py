#!/usr/bin/env python3
"""Retryable Google Drive upload for already-rendered reels.

The uploader is idempotent by exact filename within the configured folder:
before every resumable session it checks whether the mp4 already exists. It
never prints tokens, redirect URLs, response bodies, or credential values.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from km_artifacts import valid_mp4

RESULT = Path('/tmp/km_drive')
DRIVE_FILES = 'https://www.googleapis.com/drive/v3/files'
DRIVE_UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true'
MAX_ATTEMPTS = 3


class UploadError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(method, url, headers=None, data=None, timeout=60, follow_redirects=True):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


class DriveUploader:
    def __init__(self, token_url, token_secret, folder_id, requester=None, sleeper=None, attempts=MAX_ATTEMPTS):
        self.token_url = token_url
        self.token_secret = token_secret
        self.folder_id = folder_id
        self.requester = requester or _request
        self.sleep = sleeper or time.sleep
        self.attempts = attempts

    def token(self):
        status, headers, body = self.requester('POST', self.token_url,
            {'Content-Type': 'text/plain'}, self.token_secret.encode('utf-8'), 60, False)
        location = headers.get('Location') or headers.get('location')
        if 200 <= status < 300:
            try:
                token = json.loads(body.decode('utf-8')).get('token', '')
                if token:return token
            except (UnicodeDecodeError, ValueError, AttributeError):
                pass
        if not (300 <= status < 400 and location):
            raise UploadError('token endpoint returned HTTP ' + str(status) + ' or no redirect')
        # Preserve the existing two-step token exchange used by the workflow.
        self.sleep(2)
        status, _, raw = self.requester('GET', location, {}, None, 60, True)
        if not 200 <= status < 300:
            raise UploadError('token exchange returned HTTP ' + str(status))
        try:
            token = json.loads(raw.decode('utf-8')).get('token', '')
        except (UnicodeDecodeError, ValueError, AttributeError):
            token = ''
        if not isinstance(token, str) or not token:
            raise UploadError('token exchange returned no token')
        return token

    def existing_id(self, token, name):
        query = "name='{}' and '{}' in parents and trashed=false".format(name.replace("'", "\\'"), self.folder_id.replace("'", "\\'"))
        url = DRIVE_FILES + '?' + urllib.parse.urlencode({'q': query, 'fields': 'files(id,name)'})
        status, _, raw = self.requester('GET', url, {'Authorization': 'Bearer ' + token}, None, 30, True)
        if not 200 <= status < 300:
            raise UploadError('Drive lookup returned HTTP ' + str(status))
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise UploadError('Drive lookup response was invalid JSON') from None
        files = data.get('files') if isinstance(data, dict) else None
        if not isinstance(files, list):
            raise UploadError('Drive lookup response had no files list')
        for item in files:
            if isinstance(item, dict) and item.get('name') == name and item.get('id'):
                return str(item['id'])
        return ''

    def upload_once(self, path):
        name = path.name
        token = self.token()
        found = self.existing_id(token, name)
        if found:
            return found, True
        metadata = json.dumps({'name': name, 'parents': [self.folder_id]}).encode('utf-8')
        headers = {'Authorization': 'Bearer ' + token,
                   'Content-Type': 'application/json; charset=UTF-8',
                   'X-Upload-Content-Type': 'video/mp4',
                   'X-Upload-Content-Length': str(path.stat().st_size)}
        status, response_headers, _ = self.requester('POST', DRIVE_UPLOAD, headers, metadata, 60, False)
        location = response_headers.get('Location') or response_headers.get('location')
        if not (200 <= status < 300 and location):
            raise UploadError('resumable session returned HTTP ' + str(status) + ' or no session URL')
        upload_headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'video/mp4',
                          'Content-Length': str(path.stat().st_size)}
        # Stream the potentially large reel from disk. Each retry opens a fresh
        # file handle rather than keeping a full MP4 copy in runner memory.
        with path.open('rb') as media:
            status, _, raw = self.requester('PUT', location, upload_headers, media, 900, True)
        if not 200 <= status < 300:
            raise UploadError('media upload returned HTTP ' + str(status))
        try:
            file_id = json.loads(raw.decode('utf-8')).get('id', '')
        except (UnicodeDecodeError, ValueError, AttributeError):
            file_id = ''
        if not isinstance(file_id, str) or not file_id:
            raise UploadError('media upload returned no Drive file id')
        return file_id, False

    def upload(self, path):
        last = None
        for attempt in range(1, self.attempts + 1):
            try:
                return self.upload_once(Path(path))
            except Exception as exc:
                last = exc
                if attempt < self.attempts:
                    print('Drive upload retry {}/{} for {} ({})'.format(attempt, self.attempts, Path(path).name, type(exc).__name__), flush=True)
                    self.sleep(min(2 ** attempt, 8))
        raise UploadError('Drive upload failed after {} attempts ({})'.format(self.attempts, type(last).__name__ if last else 'unknown'))


def upload_all(files, env=None, requester=None, sleeper=None, result_path=None):
    env = env or os.environ
    result_path = Path(result_path or RESULT)
    files = [Path(x) for x in files if Path(x).is_file() and valid_mp4(x)]
    if not files:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text('', encoding='utf-8')
        print('No rendered mp4 files to upload.')
        return 0
    required = ('DRIVE_TOKEN_URL', 'DRIVE_TOKEN_SECRET', 'DRIVE_FOLDER_ID')
    missing = [key for key in required if not env.get(key)]
    if missing:
        rows = ['failed ' + path.name for path in files]
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
        print('Drive upload configuration missing: ' + ', '.join(missing))
        return 1
    client = DriveUploader(env['DRIVE_TOKEN_URL'], env['DRIVE_TOKEN_SECRET'], env['DRIVE_FOLDER_ID'], requester, sleeper)
    rows = []
    failed = False
    for path in sorted(files):
        try:
            file_id, existed = client.upload(path)
            rows.append('ok ' + path.name)
            action = 'already in Drive' if existed else 'uploaded to Drive'
            print('{}: {} (id {})'.format(path.name, action, file_id), flush=True)
        except Exception as exc:
            failed = True
            rows.append('failed ' + path.name)
            # Error details are type/status only; do not surface endpoint URLs or response bodies.
            print('{}: Drive upload failed after automatic retries ({})'.format(path.name, str(exc)[:180]), flush=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return 1 if failed else 0


def main():
    files = sorted((Path(__file__).resolve().parent.parent / 'out').glob('*.mp4'))
    return upload_all(files)


if __name__ == '__main__':
    sys.exit(main())
