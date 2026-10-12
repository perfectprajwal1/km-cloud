#!/usr/bin/env python3
"""KM publish: put a finished reel on km-media (GitHub Pages), wait until the public URL
serves it, then submit connected TikTok, YouTube Shorts, LinkedIn and Instagram Reels through Buffer.

Usage: python scripts/km_publish.py <story_id>
Reads : out/<id>.mp4 (if present), inbox/<id>/*.txt (platform pack)
Env   : PERSIST_POST_STATE (true in Actions), BUFFER_API_KEY, GH_PAT (secrets, never printed); optional MEDIA_REPO, MEDIA_BASE,
        POST_MODE, PLATFORMS (comma list), WAIT_SECONDS, BUFFER_API (tests only), DRY_RUN
Result: lines in /tmp/km_publish_result.txt: accepted/failed/skipped/dry_run <id> <platform> <detail>.
An accepted post is not proof of final delivery. Pending submissions are never automatically retried.
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
POSTED = "out/buffer_posted.txt"  # legacy TikTok-only ledger
RECEIPTS = "out/buffer_receipts"
PLATFORMS = ("tiktok", "youtube", "linkedin")
ALL_PLATFORMS = PLATFORMS + ("facebook", "instagram", "threads")
TIKTOK_BLOCKED = {"RV_20261011_d64xnr"}
PERSIST = os.environ.get("PERSIST_POST_STATE", "false").lower() == "true"
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
    with open(files[0], encoding="utf-8") as f:
        txt = f.read()
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
        # Credits can occur inline, not just at the start of a line.
        ln = re.split(r"(?:source|src|स्रोत|श्रोत)\s*[:：-]", ln, maxsplit=1, flags=re.I)[0]
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
        # Do not delete older media: Buffer may still be processing it.
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


def channels(key):
    orgs = gql("query { account { organizations { id name } } }", key)["account"]["organizations"]
    found = {network: [] for network in PLATFORMS}
    for o in orgs:
        for c in gql('query { channels(input: {organizationId: "%s"}) { id service name } }' % o["id"], key)["channels"]:
            service = str(c["service"]).lower()
            if service in found:
                found[service].append(c)
    return found


def platform_caption(pack, network):
    if network == "tiktok":
        return build_caption(pack)
    copy = dict(pack)
    copy["tiktok_caption"] = pack.get({"youtube": "youtube_description", "instagram": "instagram_caption", "linkedin": "linkedin_post"}[network]) or pack.get("tiktok_caption")
    return build_caption(copy)


def youtube_title(pack, caption):
    copy = dict(pack, tiktok_caption=pack.get("youtube_title") or caption.splitlines()[0], hashtags=[])
    title = build_caption(copy).replace("\n", " ").replace("<", "").replace(">", "")[:100].strip()
    if not title:
        raise Soft("YouTube title is empty")
    return title


def post_query(network, ch, pack, url):
    caption = platform_caption(pack, network)
    metadata = ""
    if network == "youtube":
        metadata = 'metadata: {youtube: {title: %s categoryId: "25" privacy: public madeForKids: false}}' % json.dumps(youtube_title(pack, caption), ensure_ascii=False)
    elif network == "instagram":
        metadata = 'metadata: {instagram: {type: reel shouldShareToFeed: true}}'
    return '''mutation CreatePost {
  createPost(input: {
    text: %s
    channelId: "%s"
    schedulingType: automatic
    mode: %s
    assets: [ { video: { url: "%s" } } ]
    %s
  }) {
    ... on PostActionSuccess { post { id status schedulingType shareMode dueAt } }
    ... on MutationError { message }
  }
}''' % (json.dumps(caption, ensure_ascii=False), ch["id"], MODE, url, metadata)


def receipt_path(sid, network):
    return os.path.join(RECEIPTS, sid + "_" + network + ".json")


def load_receipt(sid, network):
    path = receipt_path(sid, network)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if network == "tiktok" and os.path.isfile(POSTED):
        with open(POSTED) as f:
            if sid in f.read().split():
                return {"state": "accepted", "legacy": True}
    return {}


def save_receipt(sid, network, **data):
    os.makedirs(RECEIPTS, exist_ok=True)
    path = receipt_path(sid, network)
    data.update(story_id=sid, platform=network)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)
    if PERSIST:
        # Persist BEFORE the mutation. A lost response must never cause an automatic retry.
        # Both workflows share the km-reel concurrency group, including manual retries.
        for args in (["git", "add", path], ["git", "commit", "-q", "-m", "buffer receipt " + sid + " " + network]):
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise Soft("receipt checkpoint failed; no automatic retry")
        for attempt in range(3):
            if subprocess.run(["git", "push", "-q"], capture_output=True, timeout=90).returncode == 0:
                return
            # No rebase of receipt files: a conflicting ledger requires human review.
            time.sleep(5)
        raise Soft("receipt push failed; check Buffer before retrying")


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", sys.argv[1]):
        print("usage: km_publish.py <story_id>")
        return
    sid = sys.argv[1]
    key = os.environ.get("BUFFER_API_KEY", "").strip()
    pat = os.environ.get("GH_PAT", "").strip()
    try:
        if MODE not in ("shareNow", "addToQueue"):
            raise Soft("unsupported POST_MODE")
        if not key:
            if os.environ.get("PLATFORMS", "").strip() and all(v.strip() in ("facebook", "instagram", "threads") for v in os.environ["PLATFORMS"].split(",")):
                return
            raise Soft("secret BUFFER_API_KEY is empty")
        selected = [v.strip().lower() for v in os.environ.get("PLATFORMS", "").split(",") if v.strip()] or list(PLATFORMS)
        if any(v not in ALL_PLATFORMS for v in selected):
            raise Soft("invalid PLATFORMS; use tiktok,youtube,linkedin,facebook,instagram,threads")
        selected = [v for v in dict.fromkeys(selected) if v in PLATFORMS]
        if not selected:
            return
        if sid in TIKTOK_BLOCKED:
            selected = [v for v in selected if v != "tiktok"]
            # This existing test reel must never publish beyond explicit manual selection.
            if not os.environ.get("PLATFORMS", "").strip():
                print("existing test reel requires explicit platform selection; no submissions")
                return
        pack = read_pack(sid)
        discovered = channels(key)
        # Dry-run never creates drafts, publishes, uploads media, or changes receipts.
        if DRY:
            for network in selected:
                chs = discovered[network]
                if not chs:
                    continue
                if len(chs) != 1:
                    result("failed", sid, network + " expected 1 channel, found " + str(len(chs)))
                    continue
                print("DRY_RUN channel:", network, chs[0]["name"], chs[0]["id"])
                print(post_query(network, chs[0], pack, MEDIA_BASE + "/" + sid + ".mp4"))
                print("existing receipt:", load_receipt(sid, network))
                result("dry_run", sid, network + " checked; no mutation sent")
            return
        pending = []
        for network in selected:
            rec = load_receipt(sid, network)
            if rec.get("state") == "accepted":
                result("skipped", sid, network + " already accepted")
            elif rec.get("state") == "pending":
                result("failed", sid, network + " uncertain previous submission; inspect Buffer, do not blindly retry")
            elif not discovered[network]:
                continue
            elif len(discovered[network]) != 1:
                result("failed", sid, network + " expected 1 channel, found " + str(len(discovered[network])))
            else:
                pending.append(network)
        if not pending:
            return
        try:
            url = upload_media(sid, pat)
        except Exception as e:
            for network in pending:
                result("failed", sid, network + " " + secret_free(str(e), [key, pat]))
            return
        for network in pending:
            try:
                ch = discovered[network][0]
                query = post_query(network, ch, pack, url)
                save_receipt(sid, network, state="pending", channel_id=ch["id"], media_url=url)
                response = gql(query, key)["createPost"]
                if "message" in response:
                    save_receipt(sid, network, state="rejected", reason=secret_free(str(response["message"]), [key, pat]))
                    raise Soft("Buffer refused: " + str(response["message"]))
                post = response["post"]
                save_receipt(sid, network, state="accepted", channel_id=ch["id"], post_id=post["id"], status=post["status"], scheduling_type=post["schedulingType"])
                if post["schedulingType"] != "automatic":
                    result("failed", sid, network + " accepted as reminder, inspect Buffer; automatic retry blocked")
                else:
                    result("accepted", sid, network + " Buffer id=" + str(post["id"]) + " status=" + str(post["status"]))
            except Exception as e:
                result("failed", sid, network + " " + secret_free(str(e), [key, pat]))
    except Exception as e:
        for network in PLATFORMS:
            result("failed", sid, network + " " + secret_free(str(e), [key, pat]))


if __name__ == "__main__":
    main()
    try:
        import km_meta
        km_meta.run(sys.modules[__name__])
    except Exception as e:
        result("failed", sys.argv[1] if len(sys.argv) > 1 else "unknown", "meta unexpected " + type(e).__name__)
