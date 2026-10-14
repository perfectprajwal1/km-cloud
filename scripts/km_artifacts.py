#!/usr/bin/env python3
"""Restore a previously rendered reel artifact before spending time rendering again.

GitHub Actions artifacts remain the durable source for a render that did not
reach Drive. Downloads are read-only; extracted files are selected by exact
story filename and verified before being put under out/.
"""
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'out'
MAX_PAGES = 10
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_ARTIFACT_DOWNLOADS = 12


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def narration_fingerprint(story):
    cards = story.get('cards') if isinstance(story, dict) else None
    if not isinstance(cards, list) or not cards:
        return ''
    rows = []
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get('vo'), str):
            return ''
        rows.append([card['vo'], str(card.get('voice_tone', 'neutral'))])
    payload = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def valid_mp4(path):
    """Check top-level MP4 boxes rather than treating any nonempty file as a reel."""
    path = Path(path)
    try:
        size = path.stat().st_size
        if size < 24:
            return False
        found = set()
        offset = 0
        with path.open('rb') as f:
            for _ in range(256):
                if offset + 8 > size:
                    break
                f.seek(offset)
                header = f.read(8)
                if len(header) != 8:
                    return False
                box_size, kind = struct.unpack('>I4s', header)
                header_size = 8
                if box_size == 1:
                    extended = f.read(8)
                    if len(extended) != 8:
                        return False
                    box_size = struct.unpack('>Q', extended)[0]
                    header_size = 16
                elif box_size == 0:
                    box_size = size - offset
                if box_size < header_size or offset + box_size > size:
                    return False
                found.add(kind)
                offset += box_size
        return offset == size and b'ftyp' in found and b'mdat' in found and b'moov' in found
    except OSError:
        return False


def write_manifests(out_dir=None):
    out_dir = Path(out_dir or OUT)
    written = []
    for video in sorted(out_dir.glob('*.mp4')):
        sid = video.stem
        if not re.fullmatch(r'[A-Za-z0-9_-]+', sid) or not valid_mp4(video):
            print('NOTE: artifact manifest skipped for invalid/non-story mp4: ' + video.name)
            continue
        story_path = ROOT / 'stories' / (sid + '.json')
        try:
            story = json.loads(story_path.read_text(encoding='utf-8-sig'))
            fingerprint = narration_fingerprint(story)
        except (OSError, ValueError):
            fingerprint = ''
        if not fingerprint:
            print('NOTE: narration fingerprint unavailable for ' + sid + '; mp4 remains in the artifact.')
            continue
        manifest = {'story_id': sid, 'narration_sha256': fingerprint,
                    'mp4_sha256': sha256_file(video), 'size_bytes': video.stat().st_size}
        target = out_dir / (sid + '.mp4.json')
        temp = target.with_suffix(target.suffix + '.tmp')
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(target)
        written.append(sid)
    print('Artifact manifests ready: ' + (', '.join(written) if written else 'none'))
    return written


def _api_request(url, token, timeout=30):
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'km-cloud-artifact-recovery',
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def _artifact_rows(token, repo, api_url, current_run, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7, hours=1)
    rows = []
    for page in range(1, MAX_PAGES + 1):
        query = urllib.parse.urlencode({'per_page': 100, 'page': page})
        status, raw = _api_request(api_url.rstrip('/') + '/repos/' + repo + '/actions/artifacts?' + query, token)
        if status != 200:
            raise RuntimeError('artifact list returned HTTP ' + str(status))
        data = json.loads(raw.decode('utf-8'))
        items = data.get('artifacts', [])
        if not isinstance(items, list):
            raise RuntimeError('artifact list response was malformed')
        page_times = []
        for item in items:
            if not isinstance(item, dict) or item.get('expired') or int(item.get('size_in_bytes') or 0) <= 0:
                continue
            name = str(item.get('name') or '')
            if not (name.startswith('km-reels-') or name == 'reel-new' or name.startswith('reel-')):
                continue
            try:
                created = datetime.fromisoformat(str(item.get('created_at')).replace('Z', '+00:00'))
            except ValueError:
                continue
            if created < cutoff:
                continue
            run_id = str((item.get('workflow_run') or {}).get('id') or '')
            if current_run and run_id == str(current_run):
                continue
            if not item.get('archive_download_url'):
                continue
            page_times.append(created)
            rows.append(item)
        # Artifact API is newest-first. Stop after we pass the supported window.
        if items and len(page_times) == 0:
            oldest = []
            for item in items:
                try: oldest.append(datetime.fromisoformat(str(item.get('created_at')).replace('Z', '+00:00')))
                except (TypeError, ValueError): pass
            if oldest and min(oldest) < cutoff:
                break
        if len(items) < 100:
            break
    rows.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    return rows


def _download_archive(item, token, temp_dir):
    req = urllib.request.Request(item['archive_download_url'], headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'km-cloud-artifact-recovery',
    })
    target = Path(temp_dir) / ('artifact-' + str(item.get('id', 'unknown')) + '.zip')
    # The API redirects to temporary object storage. Do not forward the repo
    # token across that origin boundary; the signed redirect URL is sufficient.
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        response = opener.open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get('Location')
        if not location:
            raise RuntimeError('artifact download redirect had no location') from None
        response = urllib.request.urlopen(location, timeout=120)
    with response, target.open('wb') as out:
        length = int(response.headers.get('Content-Length') or 0)
        if length > MAX_ARCHIVE_BYTES:
            raise RuntimeError('artifact archive exceeded the safety size limit')
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise RuntimeError('artifact archive exceeded the safety size limit')
            out.write(chunk)
    return target


def _zip_member(zf, sid, suffix):
    target = sid + suffix
    found = [info for info in zf.infolist()
             if not info.is_dir() and PurePosixPath(info.filename.replace('\\', '/')).name == target]
    return found[0] if len(found) == 1 else None


def restore_pending(stories, token=None, repo=None, api_url=None, current_run=None):
    """Restore any matching prior mp4s. All API/download problems are soft fallbacks."""
    pending = {sid: story for sid, story in stories.items()
               if re.fullmatch(r'[A-Za-z0-9_-]+', sid)
               and not valid_mp4(OUT / (sid + '.mp4'))}
    if not pending:
        return set()
    token = token or os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    repo = repo or os.environ.get('GITHUB_REPOSITORY')
    api_url = api_url or os.environ.get('GITHUB_API_URL', 'https://api.github.com')
    current_run = current_run or os.environ.get('GITHUB_RUN_ID', '')
    if not token or not repo:
        print('NOTE: prior-render artifact lookup unavailable outside an authenticated GitHub Actions run.')
        return set()
    try:
        artifacts = _artifact_rows(token, repo, api_url, current_run)
    except Exception as exc:
        print('NOTE: prior-render artifact lookup failed softly (' + type(exc).__name__ + '); normal render will run.')
        return set()
    restored = set()
    downloaded = 0
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='km-artifact-') as temp_dir:
        for item in artifacts:
            if not pending:
                break
            if downloaded >= MAX_ARTIFACT_DOWNLOADS:
                print('NOTE: artifact lookup reached its recent-download limit; normal render will run for remaining stories.')
                break
            try:
                downloaded += 1
                archive = _download_archive(item, token, temp_dir)
                with zipfile.ZipFile(archive) as zf:
                    matched = {sid: _zip_member(zf, sid, '.mp4') for sid in pending}
                    matched = {sid: info for sid, info in matched.items() if info is not None}
                    if not matched:
                        continue
                    for sid, info in matched.items():
                        expected_narration = narration_fingerprint(pending[sid])
                        manifest_info = _zip_member(zf, sid, '.mp4.json')
                        manifest = None
                        if manifest_info is not None:
                            try: manifest = json.loads(zf.read(manifest_info).decode('utf-8'))
                            except (UnicodeDecodeError, ValueError): continue
                            if manifest.get('story_id') != sid or manifest.get('narration_sha256') != expected_narration:
                                continue
                        temp_video = OUT / (sid + '.mp4.restore.tmp')
                        with zf.open(info) as src, temp_video.open('wb') as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                        video_hash = sha256_file(temp_video)
                        if not valid_mp4(temp_video):
                            temp_video.unlink(missing_ok=True)
                            continue
                        if manifest is not None and (manifest.get('mp4_sha256') != video_hash or manifest.get('size_bytes') != temp_video.stat().st_size):
                            temp_video.unlink(missing_ok=True)
                            continue
                        final = OUT / (sid + '.mp4')
                        temp_video.replace(final)
                        marker_dir = OUT / '.km_artifact_restored'
                        marker_dir.mkdir(parents=True, exist_ok=True)
                        marker = {'story_id': sid, 'artifact_id': item.get('id'),
                                  'run_id': (item.get('workflow_run') or {}).get('id'),
                                  'mp4_sha256': video_hash,
                                  'narration_sha256': expected_narration,
                                  'manifest_verified': manifest is not None}
                        (marker_dir / (sid + '.json')).write_text(json.dumps(marker, indent=2) + '\n', encoding='utf-8')
                        restored.add(sid)
                        pending.pop(sid, None)
                        print('REUSED saved render artifact for ' + sid + ' (run ' + str(marker['run_id'] or 'unknown') + ').')
            except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, urllib.error.URLError) as exc:
                print('NOTE: skipped prior-render artifact ' + str(item.get('name', 'unknown')) + ' (' + type(exc).__name__ + ').')
    if pending:
        print('No valid saved render artifact found for: ' + ', '.join(sorted(pending)) + '; normal render will run.')
    return restored


if __name__ == '__main__':
    if len(os.sys.argv) > 1 and os.sys.argv[1] == 'manifest':
        write_manifests()
    else:
        raise SystemExit('Use: python scripts/km_artifacts.py manifest')
