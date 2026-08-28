# How the Beast Mode Leaderboard works

A plain-English explanation of the dashboard, for players who want to know where the
numbers come from — plus notes for Martin on the tournament software behind them.

---

## What it does

It answers one question: **what's the longest run of racks anyone has won back to back
in a single night?**

Martin Colello's tournament software already tracks that. It's the "CW" column
(consecutive wins) on every results page. But those results live on roughly 1,200
separate pages, one per tournament night, going back years. Nobody is going to open all
of them to find out who has the best run ever.

The dashboard reads all of them and puts the answer on one page.

---

## How it works, in four steps

Think of it like someone sitting down with a filing cabinet full of score sheets:

1. **Get the list.** Every Friday-night event at Natalie's — and Skip & Jan's, the same
   series under the venue's old name — is pulled from Martin's archive index.
2. **Read each night's results.** For every player: racks won, games played, streak,
   Fargo rating, finishing position.
3. **Put it in one file.** All of it gets written into a single file the web page can
   read quickly, instead of the browser fetching 250 pages.
4. **Show it.** The page sorts, searches and filters that file instantly in your browser.

This runs by itself every Saturday and Sunday morning, after Friday night's tournament.
Nobody presses a button.

**The archive is always the source of truth.** The dashboard never invents a number. If
Martin's page doesn't record something, the dashboard shows a dash rather than a guess.

---

## What it's built with

Deliberately boring, so it keeps working without maintenance:

| Part | What it is |
|---|---|
| `scrape.py` | 334 lines of Python. Reads the archive, writes the data file. No libraries to install. |
| `docs/index.html` | 259 lines — the whole website. Plain HTML, CSS and JavaScript, no frameworks. |
| `docs/data.json` | The results, about 430 KB. |
| GitHub Pages | Free hosting. |
| GitHub Actions | Free scheduled runs, twice each weekend. |

Total cost: nothing. There's no server, no database, and no account to keep alive. The
whole site is static files, so there's very little that can break.

---

## What Lightning Chip is built with

From the outside, the pages tell you a fair amount. Each one is a single block of
fixed-width text inside a `<pre>` tag, laid out in columns by padding names with spaces.
There are no tables, no styling framework, and a version stamp in the corner —
`TEXTING v10.03` on 2022 pages, `TEXTING v10.70` today. So it's a desktop program that
prints results as HTML, and it has clearly been maintained for years.

That design has a real advantage worth saying out loud: **the pages still load
instantly, still work on any phone, and pages from 2022 still open fine today.** Very
little software from 2022 can claim that.

---

## Things that could be improved in the tournament software

These all came from building the dashboard. Every one is something a person reading the
page wouldn't notice, but that quietly loses data.

**1. The winner's name gets cut off.**
On older pages the champion's row reads `Mitch Ellerm   42  1` — the name is truncated
and the Fargo rating is dropped, unlike every other row on the page. It also means the
person who won is the hardest row on the page to identify.

**2. A stray tag hides the results table.**
On many pages the column header ends with `Table <font color="black">` instead of just
`Table`. Small thing, but it broke reading the standings on **120 of 250 events** —
and because the champion sits in that block, those nights lost their winner entirely.

**3. The CW column starts partway through history.**
Pages before late 2022 end at "Number of Games Played" with no CW column. Streaks from
that era are simply gone. If old results were ever regenerated, that would recover
several years of records.

**4. Wins, games and chips often don't add up.**
A player who's knocked out loses exactly as many games as chips they started with, so
`games played − racks won` should equal their chip count. It matches exactly for 70% of
players. For the other 30% the page's own two tables disagree with each other — for
example one night lists a 3-chip player with 27 wins in 32 games, which is 5 losses.
Worth a look, since it suggests some wins aren't being counted.

**5. Two different page layouts.**
Pages from early 2022 use a completely different column layout to everything after. Any
tool reading the archive has to handle both, and the older ones are ambiguous enough
that this dashboard skips them rather than risk publishing wrong numbers.

**6. Small things that would help a lot.**
Include the full name and rating in every row; use a consistent date format (older pages
prefix the date with a timestamp); and consider publishing results as a machine-readable
file alongside the HTML. That last one would let anyone build tools like this without
guessing at column positions.

None of this affects players reading results on the night. It only matters when software
tries to read years of results at once — which is exactly what this dashboard does.

---

## Features that would be easy to add

The data is already there for all of these:

- **Player pages** — search a name, see every night they've played, their best runs and
  finishes over time.
- **Win rate leaderboard** — who wins most often, not just who has the longest streak.
- **Season view** — best run of 2025, best of 2026, rather than all-time only.
- **Doubles partners** — who plays with whom, and which pairing does best.
- **Progress charts** — a player's Fargo and results over time.
- **Head-to-head** — how often two players end up in the same event and who finishes higher.
- **Milestone alerts** — flag when someone beats their own personal best.

Bigger jobs, but possible: recovering the pre-2022 events with a second reader, and
cross-checking rack counts against the chip math.

---

## The honest caveats

- Covers the **Friday night series only** — Natalie's and Skip & Jan's. Other rooms in
  Martin's archive aren't included.
- Goes back to **July 2022**. Earlier events use the older layout and are skipped.
- **Streaks before late 2022 show a dash**, because the software wasn't recording them yet.
- **An asterisk** means the archive listed fewer total wins than the streak itself, which
  is impossible, so the total was raised to match.
- **A dagger** means a streak confirmed directly by the tournament director for a night
  that predates the CW column.

Spot something wrong? Say so and it gets fixed. Every correction so far has come from a
player noticing their own results were off.
