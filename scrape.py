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
    # Older pages prefix the date with a timestamp: "10:39:11 January 7 2022".
    s = re.sub(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s+", "", s.strip())
    m = re.match(r"([A-Za-z]+)\s+(\d+)\s+(\d{4})", s)
    if not m or m.group(1) not in MONTHS:
        return s
    return "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))


def abs_days(a, b):
    """Days between two YYYY-MM-DD strings; large if either is unparseable."""
    try:
        fa = datetime.strptime(a, "%Y-%m-%d")
        fb = datetime.strptime(b, "%Y-%m-%d")
    except (ValueError, TypeError):
        return 10 ** 6
    return abs((fa - fb).days)


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
        # Pre-2023 pages truncate the survivor's name and omit the rating
        # ("Mitch Ellerm   42  1"), so recover it via the winner heading.
        if not d["active"] and d["winner"]:
            stem = re.sub(r"\s*\(\d+\)$", "", d["winner"]).strip()
            for line in seg.group(1).split("\n"):
                t = re.sub(r"<[^>]+>", "", line).rstrip()
                mm = re.match(r"\s*([A-Za-z][A-Za-z.'\- ]+?)\s{2,}(\d+)\s+(\d+)\s*$", t)
                if mm and stem.startswith(mm.group(1).strip()):
                    d["active"].append([d["winner"], int(mm.group(2))])
                    break

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
        # The CW (consecutive wins) column only exists from late 2022 onward.
        # Older pages end at "Number of Games Played"; recording 0 there would
        # invent a streak of zero for players whose streak was never measured.
        head = re.search(r"Player Name.*?<br>", m.group(0), re.S)
        has_cw = bool(head) and "CW" in re.sub(r"<[^>]+>", "", head.group(0))
        for nm, _t, ng, cw in re.findall(
                r"([A-Za-z][^<>]*?\(\d+\))\s+(\d+:\d+)\s+(\d+)\s+(\d*)\s*<br>", m.group(0)):
            streak = (int(cw) if cw else 0) if has_cw else None
            d["avg"].append([nm.strip(), int(ng), streak])
    return d


def is_doubles(ev):
    """Scotch doubles pages list teams ("Traci T-Dennis V") with combined Fargo ratings."""
    names = [n for n, _ in ev["fargo"]] or [re.sub(r"\s*\(\d+\)$", "", a[0]) for a in ev["avg"]]
    if not names:
        return None
    dash = sum(1 for n in names if re.search(r"[A-Za-z]\s*-\s*[A-Za-z]", n)) / len(names)
    med = statistics.median([r for _, r in ev["fargo"]]) if ev["fargo"] else 0
    return dash > 0.5 or med > 750


def event_rows(ev):
    """One row per competitor: [streak, racks, name, fargo, date, place, games, adjusted].

    `streak` is the CW column -- the longest run of racks won back to back that
    night. `racks` is the night's total.

    The archive sometimes prints a streak larger than the night's total, which is
    impossible: winning N in a row requires at least N wins. In those rows the
    total is the number that is short (about 4% of games archive-wide never get a
    winner credited), so it is raised to the streak and flagged.
    """
    lut = collections.defaultdict(list)
    for full, rating in ev["fargo"]:
        lut[full[:15]].append((full, rating))
    stats = {}
    by_short = collections.defaultdict(list)
    for full, ng, cw in ev["avg"]:
        mm = re.match(r"(.*?)\s*\((\d+)\)$", full)
        if not mm:
            continue
        nm, rating = mm.group(1).strip(), int(mm.group(2))
        lut[nm[:15]].append((nm, rating))
        stats[(nm, rating)] = (cw, ng)
        by_short[nm[:15]].append((cw, ng))

    def resolve(nm):
        cands = lut.get(nm, [])
        if not cands:
            return nm, None
        fulls = collections.Counter(c[0] for c in cands)
        ratings = {c[1] for c in cands}
        best = max(fulls, key=lambda x: (fulls[x], len(x)))
        return best, (ratings.pop() if len(ratings) == 1 else None)

    def look(full, rating, key):
        # None means "no reliable row in the time table" -- unknown, not zero.
        # A short-name key is only trusted when it maps to exactly one player,
        # otherwise duplicate names silently borrow each other's numbers.
        hit = stats.get((full, rating))
        if hit is None:
            cands = by_short.get(key) or by_short.get(full[:15]) or []
            hit = cands[0] if len(cands) == 1 else None
        return hit if hit else (None, 0)

    def emit(cw, won, full, rating, place, ng):
        adjusted = 1 if (cw is not None and cw > won) else 0
        return [cw, max(won, cw) if adjusted else won, full, rating,
                ev["date"], place, ng, adjusted]

    rows = []
    for nm, won in ev["active"]:
        mm = re.match(r"(.*?)\s*\((\d+)\)$", nm)
        full = mm.group(1).strip() if mm else nm
        rating = int(mm.group(2)) if mm else None
        cw, ng = look(full, rating, full[:15])
        rows.append(emit(cw, won, full, rating, 1, ng))
    n = len(ev["elim"])
    for i, (nm, v) in enumerate(ev["elim"]):
        if not v:
            continue  # blank = duplicate registration that never played
        full, rating = resolve(nm)
        cw, ng = look(full, rating, nm)
        rows.append(emit(cw, int(v), full, rating, len(ev["active"]) + (n - i), ng))
    return rows


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as fh:
            return json.load(fh)
    return {}


# The Friday night series ran at Skip & Jan's until 2023-11-25 and moved to
# Natalie's from 2023-12-02. Same event, same tournament director, renamed venue.
VENUES = ("natalie", "skip")


def main():
    print("fetching archive index ...")
    index = fetch(BASE + "index.html")
    listed = re.findall(r'<li><a href="([^"]+)">([^<]+)</a></li>', index)

    wanted, seen = [], set()
    for url, _label in listed:
        if any(v in url.lower() for v in VENUES) and url not in seen:
            seen.add(url)
            wanted.append(url)
    print("  %d archive entries, %d for the Friday night series" % (len(listed), len(wanted)))

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
    # Collapse pages that archive the same night twice. Signatures are only
    # comparable within a few days -- an empty elimination list would otherwise
    # merge unrelated events years apart.
    by_sig = {}
    for ev in sorted(events, key=lambda e: str(e["date"])):
        sig = (ev["winner"], json.dumps(ev["elim"]))
        prev = by_sig.get(sig)
        if prev is not None and abs_days(prev["date"], ev["date"]) > 3:
            sig = (sig, ev["date"])
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
        out[k].sort(key=lambda r: (-(r[0] if r[0] is not None else -1), -r[1], r[4], r[2]))

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
