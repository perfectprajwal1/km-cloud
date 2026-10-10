#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prajwal Producer - Step 1: approval poller
==========================================
Watches the "Prajwal-Reviews" Google Sheet. Whenever a row's "approve" dropdown
is set to "approve", it downloads that row's script package from the Google Drive link
on the row, saves it into the inbox folder, and records the review_id in
produced.json so the same row is never picked up twice.

Needs nothing installed beyond Python itself (no pip packages).

One-time setup (details in the setup guide):
  1. The Google Sheet must be shared as "Anyone with the link - Viewer".
  2. The Drive folder that holds the script .txt files must be shared the
     same way (files inside inherit it automatically).

Run once to test:   py producer.py --once
Run for real:       py producer.py          (leave the window open)
Stop:               Ctrl+C
"""

import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
from datetime import datetime
from pathlib import Path

# ------------------------------ settings -----------------------------------

SPREADSHEET_ID = "1psF4P-i6XBUgf95_hB4r_QYs-29VQcasVGpJi4BoapY"

# Which tab to read. "" means "the first tab", which is right for almost
# every sheet. Only change this if the script says it cannot find the
# columns (it will tell you).
TAB_NAME = ""

# How often to check the sheet, in minutes.
POLL_MINUTES = 5

# Where things live. By default: next to this file.
BASE_DIR = Path(__file__).resolve().parent
INBOX_DIR = BASE_DIR / "inbox"          # downloaded script packages land here
STATE_FILE = BASE_DIR / "produced.json" # what we already picked up

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")

# Column letters from the live sheet (used if header names are not found).
COL_REVIEW_ID = 0     # A
COL_DRIVE_LINK = 9    # J
COL_STATUS = 10       # K

# Header names we look for first (matched lowercase, spaces -> underscore).
WANT_HEADERS = {
    "review_id": ["review_id", "review id", "id"],
    "drive": ["drive_link", "drive link", "drive", "drive_file", "drive_url"],
    "status": ["status"],
    "approve": ["approve"],
    "decision": ["decision"],
    "headline": ["original_headline", "headline", "title"],
    "story_id": ["story_id"],
}

# ------------------------------ helpers ------------------------------------

def log(msg):
    stamp = datetime.now().strftime("%H:%M:%S")
    line = "[{}] {}".format(stamp, msg)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))

def sheet_csv_url():
    url = ("https://docs.google.com/spreadsheets/d/{}/gviz/tq?tqx=out:csv"
           .format(SPREADSHEET_ID))
    if TAB_NAME:
        url += "&sheet=" + urllib.parse.quote(TAB_NAME)
    return url

_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_cookie_jar))

def http_get(url, timeout=40):
    """Return (status, headers, body_bytes). Raises only on network failure
    (no connection, DNS, timeout); HTTP error statuses come back as normal
    responses so we can print useful setup instructions for them."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = _opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    return resp.status, resp.headers, resp.read()

class SetupProblem(Exception):
    """Raised for problems Prajwal must fix manually (sharing, tab name)."""

# --------------------------- sheet reading ---------------------------------

def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _find_columns(header):
    """Map semantic names to column indexes using the header row.
    Falls back to the fixed letters A/J/K when names are missing."""
    cols = {}
    lowered = [_norm(h).replace(" ", "_") for h in header]
    for key, names in WANT_HEADERS.items():
        for name in names:
            name_n = name.replace(" ", "_")
            if name_n in lowered:
                cols[key] = lowered.index(name_n)
                break
    cols.setdefault("review_id", COL_REVIEW_ID)
    cols.setdefault("drive", COL_DRIVE_LINK)
    cols.setdefault("status", COL_STATUS)
    return cols

def fetch_approved_rows():
    """Read the sheet, return a list of dicts for rows with status=approved."""
    status, headers, body = http_get(sheet_csv_url())
    ctype = headers.get("Content-Type", "")
    if status != 200 or "csv" not in ctype.lower():
        raise SetupProblem(
            "The sheet did not answer with data (HTTP {}, {}).\n"
            "    Almost always this means link sharing is off.\n"
            "    Fix: open the sheet in Chrome -> Share button (top right)\n"
            "    -> under 'General access' choose 'Anyone with the link'\n"
            "    -> leave it on 'Viewer' -> Done. Then run me again."
            .format(status, ctype or "no content-type"))
    text = body.decode("utf-8-sig", "replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return [], []
    header = rows[0]
    # If the first row is not a header (no recognizable names), treat every
    # row as data and use the fixed column letters.
    looks_like_header = any(_norm(h) in ("review_id", "status")
                            for h in header)
    data_rows = rows[1:] if looks_like_header else rows
    cols = _find_columns(header) if looks_like_header else {
        "review_id": COL_REVIEW_ID, "drive": COL_DRIVE_LINK,
        "status": COL_STATUS}
    out = []
    for r in data_rows:
        def cell(i):
            return r[i].strip() if i < len(r) else ""
        review_id = cell(cols["review_id"])
        status_v = _norm(cell(cols["status"]))
        approve_v = _norm(cell(cols.get("approve", 999)))
        drive = cell(cols["drive"])
        if not review_id and not drive:
            continue  # blank row
        out.append({
            "review_id": review_id,
            "status": status_v,
            "approve": approve_v,
            "drive": drive,
            "decision": cell(cols.get("decision", 999)),
            "headline": cell(cols.get("headline", 999)),
            "story_id": cell(cols.get("story_id", 999)),
        })
    return out, header

# --------------------------- drive download --------------------------------

def extract_drive_id(text):
    """Pull a Drive file or folder ID out of a link or bare ID."""
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", text)
    if m:
        return "file", m.group(1)
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", text)
    if m:
        return "folder", m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", text)
    if m:
        return "file", m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{25,}", text):
        return "file", text
    return None, None

def _filename_from_headers(headers, fallback):
    cd = headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    if m:
        return urllib.parse.unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return m.group(1).strip()
    return fallback

def download_drive_file(file_id, dest_dir):
    """Download one link-shared Drive file. Returns the saved Path."""
    url = ("https://drive.google.com/uc?export=download&id=" + file_id)
    status, headers, body = http_get(url)
    # Big files first answer with an interstitial page containing a
    # confirm token. Script files are small, but handle it just in case.
    if status == 200 and b"<html" in body[:2048].lower():
        m = re.search(rb"confirm=([0-9A-Za-z_-]+)", body)
        if m:
            token = m.group(1).decode("ascii")
            status, headers, body = http_get(url + "&confirm=" + token)
    if status != 200 or b"<html" in body[:2048].lower():
        raise SetupProblem(
            "Google Drive would not give me the file (id {}).\n"
            "    Fix: in Google Drive, open the 'Prajwal Reviews' folder,\n"
            "    right-click the 'txt' folder -> Share -> 'Anyone with the\n"
            "    link' -> Viewer -> Done. Files inside inherit it.\n"
            "    Then run me again.".format(file_id))
    name = _filename_from_headers(headers, "script-{}.txt".format(file_id))
    name = re.sub(r'[\\/:*?"<>|]', "_", name)  # Windows-safe
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    dest.write_bytes(body)
    return dest

# ------------------------------ state --------------------------------------

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log("WARNING: produced.json was unreadable, starting fresh.")
    return {"produced": {}}

def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(STATE_FILE)

# ------------------------------ main logic ---------------------------------

def poll_once(state):
    """One check of the sheet. Returns number of new packages fetched."""
    rows, header = fetch_approved_rows()
    # Trigger = the far-right "approve" dropdown column (value "approve").
    approved = [r for r in rows if r["approve"] == "approve"]
    produced = state["produced"]
    new_count = 0
    log("Sheet read OK: {} rows, {} approved, {} already produced.".format(
        len(rows), len(approved),
        sum(1 for r in approved if r["review_id"] in produced)))
    for row in approved:
        rid = row["review_id"] or row["story_id"] or row["drive"]
        if not rid:
            log("Skipping an approved row with no review_id.")
            continue
        if rid in produced:
            continue
        kind, drive_id = extract_drive_id(row["drive"])
        if kind == "folder":
            log("Row {}: the Drive cell is a FOLDER link - tell Instinct,"
                " the producer needs per-file links. Skipping.".format(rid))
            continue
        if not drive_id:
            log("Row {}: approved but no usable Drive link in column J. "
                "Skipping.".format(rid))
            continue
        log("New approved row: {}{}".format(
            rid, " - " + row["headline"][:60] if row["headline"] else ""))
        dest_dir = INBOX_DIR / rid
        try:
            saved = download_drive_file(drive_id, dest_dir)
        except SetupProblem:
            raise
        except Exception as e:
            log("Row {}: download failed ({}). Will retry next poll."
                .format(rid, e))
            continue
        meta = dict(row)
        meta["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        (dest_dir / "row.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        produced[rid] = {"fetched_at": meta["fetched_at"],
                         "file": str(saved.name),
                         "headline": row["headline"]}
        save_state(state)
        new_count += 1
        log("Saved package: {}".format(saved))
    return new_count

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    once = "--once" in sys.argv
    log("Producer poller started. Sheet: {}".format(SPREADSHEET_ID))
    state = load_state()
    log("Already produced: {} package(s). Inbox: {}".format(
        len(state["produced"]), INBOX_DIR))
    failures = 0
    while True:
        try:
            n = poll_once(state)
            failures = 0
            if n:
                log("Done: {} new package(s) in the inbox.".format(n))
            else:
                log("Nothing new.")
        except SetupProblem as e:
            log("SETUP NEEDED:\n    " + str(e).replace("\n", "\n    "))
            log("Fix the above, then just run me again. Exiting.")
            return 2
        except KeyboardInterrupt:
            raise
        except Exception as e:
            failures += 1
            log("Poll failed ({}): {}".format(type(e).__name__, e))
            if failures >= 5:
                log("5 failures in a row - check the internet connection "
                    "and that the sheet still opens in Chrome. Exiting.")
                return 3
        if once:
            return 0
        wait = POLL_MINUTES * 60 if failures == 0 else 120
        log("Next check in {} min. (Ctrl+C to stop)".format(wait // 60))
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            log("Stopped by user. Bye.")
            return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Stopped by user. Bye.")
