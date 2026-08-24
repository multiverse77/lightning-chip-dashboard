#!/usr/bin/env python3
"""Scrape Natalie's chip tournaments from lightningchip.xyz into docs/data.json."""

import collections
import html as htmllib
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = "https://lightningchip.xyz/results/Archive/"
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(ROOT, "cache", "events.json")
OUT_PATH = os.path.join(ROOT, "docs", "data.json")

UA = "lightning-chip-dashboard/1.0 (fan-made stats page; contact via github issues)"
WORKERS = 4
ALWAYS_REFRESH = 6  # newest N events are re-fetched in case results were still being entered

MONTHS = {m: i + 1 for i, m in enumerate(
    "January February March April May June July August September October November December".split())}


def fetch(url, attempts=3):
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            if i == attempts - 1:
                raise
            time.sleep(2 * (i + 1))


def norm_date(s):
    m = re.match(r"([A-Za-z]+)\s+(\d+)\s+(\d{4})", s.strip())
    if not m:
        return s.strip()
    return "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))


def parse_event(raw, filename):
    """Extract standings from one archived tournament page.

    Layout is fixed-width text inside <pre>: the red block lists eliminated
    players in elimination order as 20-char cells of "name(17) racks-won".
    """
    d = {"file": filename}
    m = re.search(r"<h3>(.*?)</h3>\s*(.*?)<br>", raw, re.S)
    d["title"] = htmllib.unescape(re.sub("<[^>]+>", "", m.group(1))).strip() if m else ""
    d["date"] = norm_date(m.group(2)) if m else ""

    m = re.search(r"Tournament winner:\s*(.*?)</h3>", raw, re.S)
    d["winner"] = htmllib.unescape(re.sub("<[^>]+>", "", m.group(1))).strip() if m else ""

    d["active"] = []
    seg = re.search(r"Table\s*\n(.*?)<p style=\"color:red\">", raw, re.S)
    if seg:
        for line in seg.group(1).split("\n"):
            t = re.sub(r"<[^>]+>", "", line).rstrip()
            mm = re.match(r"\s*(.+?\(\d+\))\s+(\d+)\s+(\d+)\s*$", t)
            if mm:
                d["active"].append([mm.group(1).strip(), int(mm.group(2))])

    d["elim"] = []
    m = re.search(r"<p style=\"color:red\">(.*?)</p>", raw, re.S)
    if m:
        for line in m.group(1).strip("\n").split("\n"):
            for i in range(0, len(line), 20):
                cell = line[i:i + 20]
                if cell.strip():
                    d["elim"].append([cell[:17].strip(), cell[17:].strip()])

    d["fargo"] = []
    m = re.search(r"Fargo List:.*?<br>\n(.*?)</p>", raw, re.S)
    if m:
        txt = re.sub(r"<[^>]+>", "", m.group(1))
        for line in txt.split("\n"):
            for i in range(0, len(line), 30):
                cell = line[i:i + 30].strip()
                mm = re.match(r"(.*?)\s+\((\d+)\)$", cell) if cell else None
                if mm:
                    d["fargo"].append([mm.group(1).strip(), int(mm.group(2))])

    d["avg"] = []
    m = re.search(r"Average Time Per Game:.*?</p>", raw, re.S)
    if m:
        for nm, _t, ng, _cw in re.findall(
                r"([A-Za-z][^<]*?\(\d+\))\s+(\d+:\d+)\s+(\d+)\s+(\d*)\s*<br>", m.group(0)):
            d["avg"].append([nm.strip(), int(ng)])
    return d


def is_doubles(ev):
    """Scotch doubles pages list teams ("Traci T-Dennis V") with combined Fargo ratings."""
    names = [n for n, _ in ev["fargo"]] or [re.sub(r"\s*\(\d+\)$", "", n) for n, _ in ev["avg"]]
    if not names:
        return None
    dash = sum(1 for n in names if re.search(r"[A-Za-z]\s*-\s*[A-Za-z]", n)) / len(names)
    med = statistics.median([r for _, r in ev["fargo"]]) if ev["fargo"] else 0
    return dash > 0.5 or med > 750


def event_rows(ev):
    """One row per competitor: [racks_won, name, fargo, date, finishing_place]."""
    lut = collections.defaultdict(list)
    for full, rating in ev["fargo"]:
        lut[full[:15]].append((full, rating))
    for full, _ng in ev["avg"]:
        mm = re.match(r"(.*?)\s*\((\d+)\)$", full)
        if mm:
            lut[mm.group(1).strip()[:15]].append((mm.group(1).strip(), int(mm.group(2))))

    def resolve(nm):
        cands = lut.get(nm, [])
        if not cands:
            return nm, None
        fulls = collections.Counter(c[0] for c in cands)
        ratings = {c[1] for c in cands}
        best = max(fulls, key=lambda x: (fulls[x], len(x)))
        return best, (ratings.pop() if len(ratings) == 1 else None)

    rows = []
    for nm, won in ev["active"]:
        mm = re.match(r"(.*?)\s*\((\d+)\)$", nm)
        rows.append([won, mm.group(1).strip() if mm else nm,
                     int(mm.group(2)) if mm else None, ev["date"], 1])
    n = len(ev["elim"])
    for i, (nm, v) in enumerate(ev["elim"]):
        if not v:
            continue  # blank = duplicate registration that never played
        full, rating = resolve(nm)
        rows.append([int(v), full, rating, ev["date"], len(ev["active"]) + (n - i)])
    return rows


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as fh:
            return json.load(fh)
    return {}


def main():
    print("fetching archive index ...")
    index = fetch(BASE + "index.html")
    listed = re.findall(r'<li><a href="([^"]+)">([^<]+)</a></li>', index)

    wanted, seen = [], set()
    for url, _label in listed:
        if "natalie" in url.lower() and url not in seen:
            seen.add(url)
            wanted.append(url)
    print("  %d archive entries, %d for Natalie's" % (len(listed), len(wanted)))

    cache = load_cache()
    stale = set(wanted[:ALWAYS_REFRESH])
    todo = [u for u in wanted if u not in cache or u in stale]
    print("  cached: %d, fetching: %d" % (len(wanted) - len(todo), len(todo)))

    if todo:
        def grab(u):
            time.sleep(0.15)
            try:
                return u, parse_event(fetch(BASE + u), u)
            except Exception as exc:  # one bad page must not sink the whole run
                print("  WARN %s: %s" % (u, exc))
                return u, None

        failed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for u, ev in pool.map(grab, todo):
                if ev is not None:
                    cache[u] = ev
                elif u not in cache:
                    failed += 1
        if failed:
            print("  %d page(s) unavailable and not cached; skipped" % failed)
        if not cache:
            raise SystemExit("nothing could be fetched -- refusing to write empty data")

    for gone in set(cache) - set(wanted):
        del cache[gone]

    if len(cache) < 0.8 * len(wanted):
        raise SystemExit("only %d/%d events available -- refusing to publish a partial archive"
                         % (len(cache), len(wanted)))

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as fh:
        json.dump(cache, fh, separators=(",", ":"), sort_keys=True)

    # Drop demo runs, then collapse pages that archive the same night twice.
    events = [ev for u, ev in cache.items() if "demo" not in u.lower()]
    by_sig = {}
    for ev in events:
        sig = (ev["winner"], json.dumps(ev["elim"]))
        prev = by_sig.get(sig)
        if prev is None or (len(ev["avg"]), ev["date"]) > (len(prev["avg"]), prev["date"]):
            by_sig[sig] = ev
    events = sorted(by_sig.values(), key=lambda e: e["date"], reverse=True)

    out = {"singles": [], "doubles": []}
    meta = []
    for ev in events:
        dbl = is_doubles(ev)
        if dbl is None:
            continue
        fmt = "doubles" if dbl else "singles"
        rows = event_rows(ev)
        if not rows:
            continue
        out[fmt].extend(rows)
        meta.append({"date": ev["date"], "title": ev["title"], "format": fmt,
                     "entrants": len(rows), "winner": ev["winner"]})

    for k in out:
        out[k].sort(key=lambda r: (-r[0], r[3], r[1]))

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": BASE,
        "events": meta,
        "rows": out,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    ns = sum(1 for m in meta if m["format"] == "singles")
    nd = len(meta) - ns
    print("wrote %s" % OUT_PATH)
    print("  %d singles events (%d results), %d doubles events (%d results)"
          % (ns, len(out["singles"]), nd, len(out["doubles"])))
    if meta:
        print("  latest: %s  %s" % (meta[0]["date"], meta[0]["title"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
