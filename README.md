# Natalie's Chip Tournament — Beast Mode Leaderboard

An auto-updating leaderboard of the longest back-to-back rack runs per player per night
at the Friday night nine-ball chip tournaments -- Natalie's today, Skip & Jan's before
December 2023 -- scraped from Martin Colello's
[Lightning Chip archive](https://lightningchip.xyz/results/Archive/).

**Live page:** <https://multiverse77.github.io/lightning-chip-dashboard/>

## One-time setup

```bash
cd ~/lightning-chip-dashboard
git push -u origin main
```

The remote is already set to `https://github.com/multiverse77/lightning-chip-dashboard.git`.
Create that repo on github.com first, as **public** — GitHub Pages is only free on public
repos. When `git push` asks for a password, paste a Personal Access Token, not your
account password (GitHub stopped accepting passwords for git in 2021). Generate one at
**Settings → Developer settings → Personal access tokens → Fine-grained tokens** with
*Contents: read and write* on this repository.

Then in the repo on github.com:

1. **Settings → Pages** → Source: *Deploy from a branch*, Branch: `main`, Folder: `/docs`. Save.
2. **Settings → Actions → General** → Workflow permissions: *Read and write permissions*. Save.
3. **Actions** tab → *Refresh tournament data* → *Run workflow* to confirm it works.

The page is live a minute later. Share the URL — no login needed to view it.

## How it updates

`.github/workflows/update.yml` runs `scrape.py` at 08:00 Arizona time on Saturday and
Sunday, which is after Friday night's tournament. If anything changed it commits
`docs/data.json` and GitHub Pages redeploys automatically. You can also trigger it by
hand from the Actions tab.

`cache/events.json` stores every event already parsed, so a weekly run only re-fetches
the six most recent pages (results are sometimes still being entered when a page is
first archived). A full cold rebuild is ~148 requests and takes about 10 seconds.

## Files

| Path | What it is |
| --- | --- |
| `scrape.py` | Fetches the archive, parses the fixed-width standings, writes `docs/data.json` |
| `docs/index.html` | The dashboard — vanilla JS, no dependencies, no CDN |
| `docs/data.json` | Generated payload (~240 KB, ~59 KB gzipped) |
| `cache/events.json` | Parsed-event cache so reruns stay cheap |

Run it locally with `python3 scrape.py` (standard library only), then
`python3 -m http.server -d docs` and open <http://localhost:8000>.

## How the numbers are derived

Each archived page is fixed-width text inside a `<pre>` block. The red section lists
players in **elimination order** as 20-character cells of `name(17) + racks-won`; the
row above it holds the surviving winner and their rack count.

- **In a row** = the archive's `CW` column: the longest run of racks won back to
  back that night. Confirmed by reproducing Lyle Wilson's public "Cons. Wins"
  table from Skips Friday nights — 18 of 23 rows matched on Fargo, streak *and*
  games played.
- **Racks** = games that player won across the whole night, streak or not.
- **Finish** = placing, reconstructed from elimination order. Verified against the
  "Second place" header on all 69 events that publish one — 69/69 matched.
- Racks-won never exceeded that player's games played across 3,549 checked rows.

Singles and Scotch doubles are told apart by **page content, not filename**, because
several events are mislabelled at the source — e.g.
`Natalies9BallScotchDoublesChipTournamentJune7th2024` is actually a singles event.
Doubles pages list teams (`Traci T-Dennis V`) with combined Fargo ratings around 950+;
singles pages list individuals around 490.

## Known data quirks

These come from the source archive and are deliberately left alone:

- Names are spelled inconsistently (`Joven Bustamante` / `Bustemante`,
  `Nicholas` / `NIcholas De Leon`). Merging them would mean guessing.
- Names are truncated to 15 characters in the standings block; the full spelling is
  recovered from the Fargo list on the same page where it is unambiguous.
- Blank rack counts are duplicate registrations that never played, and are skipped.
- Two `MikePowersDemo` events are excluded, as is one page that archives the
  2026-03-27 event a second time.
- Roughly 3% of games don't reconcile against the per-player time table. That gap is in
  the source data, not the parser.
- The archive credits a winner to only ~96% of games played (1,014 of 24,389 singles
  games have no win recorded). Consequently 26 singles and 7 doubles rows print a streak
  larger than the night's rack total, which is impossible. The streak column is the sound
  one -- it never exceeds games played in any of 3,507 rows -- so the total is raised to
  the streak and marked with an asterisk. Nothing else is altered.
- Rows whose name can't be matched to exactly one entry in the time table show a dash
  rather than a guessed value. A genuine zero (player won nothing) renders as 0.
- The archive's CW column only appears from late 2022. Earlier pages end at "Number of
  Games Played", so their streaks are unknown (dash), not zero. Rack totals still count.
- 24 pages from Jan-Jul 2022 use an older multi-column layout whose fixed-width cells
  parse into garbage ("Bret H Priscilla" / "H ("). They are skipped rather than guessed
  at. They predate the CW column, so they could not contribute a streak regardless.
- Beware Lyle Wilson's widely-shared 2023 spreadsheet: its "Cons. Wins" column mixes
  real CW values with the plain Won column for nights that predate CW. Mitch Ellerman's
  42 is a rack total from a 45-game night he lost 3 of -- not a 42-rack streak.

## Being a good neighbour

The scraper identifies itself, retries with backoff, uses four workers with a small
delay, and caches so it isn't re-downloading the whole archive. If you want it to run
more often, cache harder rather than raising the worker count. It's worth telling
Martin the page exists — he built the tournament software this all comes from.
