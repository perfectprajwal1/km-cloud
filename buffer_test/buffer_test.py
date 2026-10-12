#!/usr/bin/env python3
"""KM Buffer test: find organization + TikTok channel, post ONE test reel.
Key comes from env BUFFER_API_KEY (never printed). Stdlib only."""
import json, os, re, sys, urllib.request, urllib.error

API = "https://api.buffer.com"
KEY = os.environ.get("BUFFER_API_KEY", "").strip()
MEDIA_URL = os.environ.get("MEDIA_URL", "").strip()
MODE = os.environ.get("POST_MODE", "shareNow").strip()      # shareNow | addToQueue
SERVICE = os.environ.get("CHANNEL_SERVICE", "tiktok").strip().lower()
DRY = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
CAPTION_FILE = os.environ.get("CAPTION_FILE", "buffer_test/caption.txt")
MAX_TAGS = 5


def die(msg):
    print("FAIL:", msg)
    sys.exit(1)


def gql(query):
    req = urllib.request.Request(
        API, data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
    except urllib.error.HTTPError as e:
        # print status and body only (headers could echo nothing secret, but stay minimal)
        die("HTTP %s from Buffer: %s" % (e.code, e.read().decode()[:600]))
    except Exception as e:
        die("request error: %s" % type(e).__name__)
    data = json.loads(body)
    if data.get("errors"):
        die("GraphQL errors: %s" % json.dumps(data["errors"])[:800])
    return data["data"]


def trim_caption(text):
    """Keep at most MAX_TAGS hashtags (Buffer/TikTok limit). Drops the extras, keeps order."""
    seen = 0
    out = []
    for tok in text.split(" "):
        if tok.startswith("#"):
            seen += 1
            if seen > MAX_TAGS:
                continue
        out.append(tok)
    return " ".join(out).strip()


def check_media(url):
    """Must be https, 200, video type, NO redirect."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"Range": "bytes=0-1023"})
    try:
        r = op.open(req, timeout=60)
    except urllib.error.HTTPError as e:
        die("media URL returned HTTP %s (redirects count as failure)" % e.code)
    except Exception as e:
        die("media URL unreachable: %s" % type(e).__name__)
    ctype = r.headers.get("Content-Type", "")
    print("media check: HTTP %s content-type=%s" % (r.status, ctype))
    if r.status not in (200, 206) or "video" not in ctype.lower():
        die("media URL is not a direct public video")


def main():
    if not KEY:
        die("secret BUFFER_API_KEY is empty or missing")
    if not MEDIA_URL.startswith("https://"):
        die("MEDIA_URL must be an https URL")
    if MODE not in ("shareNow", "addToQueue"):
        die("POST_MODE must be shareNow or addToQueue")

    with open(CAPTION_FILE, encoding="utf-8") as f:
        caption = trim_caption(f.read().strip())
    print("hashtags used:", len(re.findall(r"#\S+", caption)), "(max %d)" % MAX_TAGS)

    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    print("organizations found:", [(o["id"], o["name"]) for o in orgs])
    if not orgs:
        die("no organizations on this key")

    matches = []
    for o in orgs:
        chans = gql('query { channels(input: {organizationId: "%s"}) '
                    '{ id name displayName service isQueuePaused } }' % o["id"])["channels"]
        for c in chans:
            print("channel: org=%s id=%s service=%s name=%s paused=%s" % (
                o["id"], c["id"], c["service"], c.get("displayName") or c.get("name"), c.get("isQueuePaused")))
            if str(c["service"]).lower() == SERVICE:
                matches.append(c)
    if len(matches) != 1:
        die("expected exactly 1 %s channel, found %d" % (SERVICE, len(matches)))
    ch = matches[0]

    check_media(MEDIA_URL)
    if DRY:
        print("DRY_RUN=true: stopping before createPost. Channel id:", ch["id"])
        return

    q = '''mutation CreatePost {
  createPost(input: {
    text: %s
    channelId: "%s"
    schedulingType: automatic
    mode: %s
    assets: [ { video: { url: "%s" } } ]
  }) {
    ... on PostActionSuccess { post { id status schedulingType shareMode dueAt channelService text } }
    ... on MutationError { message }
  }
}''' % (json.dumps(caption, ensure_ascii=False), ch["id"], MODE, MEDIA_URL)
    res = gql(q)["createPost"]
    if "message" in res:
        die("Buffer refused the post: %s" % res["message"])
    p = res["post"]
    print("POST CREATED id=%s" % p["id"])
    print("schedulingType returned:", p["schedulingType"])
    print("status returned:", p["status"])
    print("shareMode:", p["shareMode"], "dueAt:", p.get("dueAt"))
    if p["schedulingType"] != "automatic":
        print("WARNING: not automatic. Buffer would only send a phone reminder.")


if __name__ == "__main__":
    main()
