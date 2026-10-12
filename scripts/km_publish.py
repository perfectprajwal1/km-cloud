#!/usr/bin/env python3
"""KM publish: put a finished reel on km-media (GitHub Pages), wait until the public URL
serves it, then post it to the TikTok channel through Buffer.

Usage: python scripts/km_publish.py <story_id>
Reads : out/<id>.mp4 (if present), inbox/<id>/*.txt (platform pack)
Env   : BUFFER_API_KEY, GH_PAT (secrets, never printed); optional MEDIA_REPO, MEDIA_BASE,
        POST_MODE, KEEP_FILES, WAIT_SECONDS, BUFFER_API (tests only), DRY_RUN
Result: appends one line to /tmp/km_publish_result.txt:  "posted <id> <status>" or "failed <id> <why>"
Always exits 0: a publishing problem must never fail the render or lose the Drive copy.
"""
import base64, glob, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.error, urllib.request

MEDIA_REPO = os.environ.get("MEDIA_REPO", "perfectprajwal1/km-media")
MEDIA_BASE = os.environ.get("MEDIA_BASE", "https://perfectprajwal1.github.io/km-media").rstrip("/")
REPO_URL = os.environ.get("MEDIA_REPO_URL", "https://github.com/%s.git" % MEDIA_REPO)
API = os.environ.get("BUFFER_API", "https://api.buffer.com")
MODE = os.environ.get("POST_MODE", "shareNow")
KEEP = int(os.environ.get("KEEP_FILES", "30"))
WAIT = int(os.environ.get("WAIT_SECONDS", "720"))
DRY = os.environ.get("DRY_RUN", "false").lower() == "true"
POSTED = "out/buffer_posted.txt"
RESULT = "/tmp/km_publish_result.txt"
MAX_TAGS = 5
MAX_LEN = 2200
SRC_LINE = re.compile(r"^\s*(source|src|स्रोत|श्रोत)\s*[:：-]", re.I)
URL_RE = re.compile(r"https?://\S+")


class Soft(Exception):
    pass


def result(kind, sid, why=""):
    line = ("%s %s %s" % (kind, sid, why)).strip()
    print("RESULT:", line)
    with open(RESULT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def secret_free(text, secrets):
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


# ---------- caption ----------
def read_pack(sid):
    files = sorted(glob.glob("inbox/%s/*.txt" % sid))
    if not files:
        raise Soft("no package txt in inbox/%s" % sid)
    txt = open(files[0], encoding="utf-8").read()
    marker = "--- PLATFORM PACK (JSON) ---"
    i = txt.find(marker)
    if i < 0:
        raise Soft("no PLATFORM PACK in package")
    obj, _ = json.JSONDecoder().raw_decode(txt[i + len(marker):].lstrip())
    return obj


def build_caption(pack):
    """tiktok_caption without any source credit, plus hashtags, max 5 hashtags in total."""
    base = str(pack.get("tiktok_caption") or pack.get("instagram_caption") or "")
    credit = str(pack.get("source_credit") or "").strip()
    lines = []
    for ln in base.replace("\r", "").split("\n"):
        if SRC_LINE.match(ln):
            continue
        if credit:
            ln = ln.replace(credit, "")
        ln = URL_RE.sub("", ln).strip()
        if ln:
            lines.append(ln)
    text = "\n".join(lines).strip()
    tags = [t for t in re.findall(r"#\S+", text)]
    for h in pack.get("hashtags") or []:
        h = str(h).strip()
        if h and not h.startswith("#"):
            h = "#" + h
        if h and h.lower() not in [t.lower() for t in tags]:
            tags.append(h)
            text = (text + " " + h).strip()
    # enforce max tags: drop extras from the end, keep order
    seen, out = 0, []
    for tok in re.split(r"(\s+)", text):
        if tok.startswith("#"):
            seen += 1
            if seen > MAX_TAGS:
                continue
        out.append(tok)
    text = re.sub(r"[ \t]+\n", "\n", "".join(out)).strip()
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN].rstrip()
    if not text:
        raise Soft("caption came out empty")
    return text


# ---------- km-media upload ----------
def git(args, cwd, pat, check=True):
    hdr = "AUTHORIZATION: basic " + base64.b64encode(("x-access-token:" + pat).encode()).decode()
    cmd = ["git", "-c", "http.extraheader=" + hdr] + args
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    if check and p.returncode != 0:
        raise Soft("git %s failed: %s" % (args[0], secret_free((p.stdout + p.stderr).strip()[-300:], [pat, hdr])))
    return p


def url_ready(url, size=None):
    """200, video type, no redirect, and (if known) the full size."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(NoRedirect)
    try:
        r = op.open(urllib.request.Request(url, method="HEAD"), timeout=30)
    except Exception:
        return False
    ctype = r.headers.get("Content-Type", "").lower()
    clen = r.headers.get("Content-Length")
    if r.status != 200 or "video" not in ctype:
        return False
    if size and clen and int(clen) != size:
        return False
    return True


def upload_media(sid, pat):
    name = sid + ".mp4"
    url = "%s/%s" % (MEDIA_BASE, name)
    local = "out/" + name
    size = os.path.getsize(local) if os.path.isfile(local) and os.path.getsize(local) else None
    if url_ready(url, size):
        print("media already live:", url)
        return url
    if not size:
        raise Soft("no local mp4 and URL not live (%s)" % url)
    if not pat:
        raise Soft("secret GH_PAT is empty")
    tmp = tempfile.mkdtemp(prefix="kmmedia_")
    try:
        git(["clone", "-q", "--depth", "1", REPO_URL, tmp], None, pat)
        git(["config", "user.name", "km-cloud"], tmp, pat)
        git(["config", "user.email", "km-cloud@users.noreply.github.com"], tmp, pat)
        shutil.copyfile(local, os.path.join(tmp, name))
        # keep the repo small: newest KEEP reels stay (ids start with a date, so name order = age order)
        mp4s = sorted(f for f in os.listdir(tmp) if f.endswith(".mp4"))
        for old in [f for f in mp4s if f != name][:max(0, len(mp4s) - KEEP)]:
            git(["rm", "-q", old], tmp, pat, check=False)
        git(["add", "-A"], tmp, pat)
        git(["commit", "-q", "-m", "reel " + sid], tmp, pat)
        ok = False
        for i in range(3):
            if git(["push", "-q", "origin", "HEAD"], tmp, pat, check=False).returncode == 0:
                ok = True
                break
            git(["pull", "-q", "--rebase"], tmp, pat, check=False)
            time.sleep(5)
        if not ok:
            raise Soft("push to km-media failed 3 times (check GH_PAT rights on km-media)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    t0 = time.time()
    while time.time() - t0 < WAIT:
        if url_ready(url, size):
            print("media live after %ds: %s" % (time.time() - t0, url))
            return url
        time.sleep(15)
    raise Soft("media URL not live after %ds (Pages still building?)" % WAIT)


# ---------- Buffer ----------
def gql(query, key):
    req = urllib.request.Request(
        API, data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise Soft("Buffer HTTP %s: %s" % (e.code, secret_free(e.read().decode()[:300], [key])))
    except Exception as e:
        raise Soft("Buffer request error: %s" % type(e).__name__)
    if data.get("errors"):
        raise Soft("Buffer errors: %s" % secret_free(json.dumps(data["errors"])[:400], [key]))
    return data["data"]


def tiktok_channel(key):
    orgs = gql("query { account { organizations { id name } } }", key)["account"]["organizations"]
    found = []
    for o in orgs:
        for c in gql('query { channels(input: {organizationId: "%s"}) { id service name } }' % o["id"], key)["channels"]:
            if str(c["service"]).lower() == "tiktok":
                found.append(c)
    if len(found) != 1:
        raise Soft("expected exactly 1 TikTok channel in Buffer, found %d" % len(found))
    return found[0]


def post_buffer(caption, url, key):
    ch = tiktok_channel(key)
    q = '''mutation CreatePost {
  createPost(input: {
    text: %s
    channelId: "%s"
    schedulingType: automatic
    mode: %s
    assets: [ { video: { url: "%s" } } ]
  }) {
    ... on PostActionSuccess { post { id status schedulingType shareMode dueAt } }
    ... on MutationError { message }
  }
}''' % (json.dumps(caption, ensure_ascii=False), ch["id"], MODE, url)
    res = gql(q, key)["createPost"]
    if "message" in res:
        raise Soft("Buffer refused the post: %s" % res["message"])
    p = res["post"]
    print("Buffer post id=%s status=%s schedulingType=%s" % (p["id"], p["status"], p["schedulingType"]))
    if p["schedulingType"] != "automatic":
        raise Soft("Buffer made a reminder, not an auto-post (schedulingType=%s)" % p["schedulingType"])
    return p


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", sys.argv[1]):
        print("usage: km_publish.py <story_id>")
        return
    sid = sys.argv[1]
    key = os.environ.get("BUFFER_API_KEY", "").strip()
    pat = os.environ.get("GH_PAT", "").strip()
    try:
        if os.path.isfile(POSTED) and sid in open(POSTED).read().split():
            print("already posted to Buffer, skipping:", sid)
            return
        if not key:
            raise Soft("secret BUFFER_API_KEY is empty")
        caption = build_caption(read_pack(sid))
        print("caption (%d chars, %d hashtags):" % (len(caption), len(re.findall(r"#\S+", caption))))
        print(caption)
        url = upload_media(sid, pat)
        if DRY:
            print("DRY_RUN: stopping before Buffer. Media URL:", url)
            return
        p = post_buffer(caption, url, key)
        os.makedirs("out", exist_ok=True)
        with open(POSTED, "a") as f:
            f.write(sid + "\n")
        result("posted", sid, p["status"])
    except Soft as e:
        result("failed", sid, str(e))
    except Exception as e:  # never break the render
        result("failed", sid, "unexpected %s" % type(e).__name__)


if __name__ == "__main__":
    main()
