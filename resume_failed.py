#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resume the oldest unfinished approved stories through the normal reel path."""
import re
import subprocess
import sys
from pathlib import Path
import make_reel

ROOT = Path(__file__).resolve().parent
NPM = make_reel.NPM
run = make_reel.run

def voice_and_render(rid, recover=False):
    make_reel.ROOT = ROOT
    make_reel.run = run
    return make_reel.voice_and_render(rid, recover=recover)


def main():
    args = sys.argv[1:]
    if len(args) > 1 or (args and not re.fullmatch(r'[A-Za-z0-9_-]+', args[0])):
        print('Use: py resume_failed.py [REVIEW_ID]')
        return 2
    # Keep the one-command recovery interface while sharing the same
    # per-story continuation and artifact-reuse path as make_reel.py.
    make_reel.ROOT = ROOT
    make_reel.run = run
    if args:
        rid = args[0]
        dp = ROOT / 'out' / 'done.txt'
        done = set(dp.read_text(encoding='utf-8').split()) if dp.exists() else set()
        if rid in done:
            print('Already in Drive: ' + rid + '. No voice request or render.')
            return 0
        if not (ROOT / 'inbox' / rid).is_dir():
            print('No saved approved inbox folder for ' + rid + '.')
            return 2
        ids = [rid]
    else:
        ids = make_reel.pending_ids(limit=5)
        if not ids:
            print('Nothing unfinished. No voice request made.')
            return 0
        print('Default: oldest unfinished approved stories, up to five; each is attempted independently.', flush=True)
    return make_reel.process_stories(ids, recover=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Stopped. Saved audio and attempt markers kept.')
        sys.exit(3)
    except Exception as exc:
        print('Resume launcher error: ' + type(exc).__name__ + ': ' + str(exc)[:220])
        sys.exit(2)
