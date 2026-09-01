# Data and cohort reference

This document records what the downloaded TFMStats/“Stranded Knight” snapshot contains, how the old Starting Hand numbers are reproduced, and how this app's competitive defaults differ.

## Local source

- Download endpoint: `https://api.tfmstats.com/api/download-db`
- Archive: `data/tfmstats_db.zip` (about 364 MiB)
- Extracted data: `data/tfmstats_db/` (about 364 MiB, 18 Parquet tables)
- Current snapshot timestamp: `2026-08-30T09:34:36Z`
- Snapshot size: 248,813 total tables in `games_canonical`; the Starting Hand reference cohort contains 186,815 distinct games and 3,727,660 card offers.

Queries run locally with DuckDB. The generated cohort CSVs contain only aggregates, so they are small and do not duplicate the raw 364 MiB dataset.

## Relevant tables

| Table | Fields used | Meaning |
|---|---|---|
| `games_canonical` | `TableId`, `GameMode`, `Map`, `PreludeOn`, `ColoniesOn`, `DraftOn` | Game options and map |
| `gamestats` | `TableId`, `PlayerCount`, `UpdatedAt` | Player count and snapshot metadata |
| `gameplayers_canonical` | `TableId`, `PlayerId`, `Position`, `Elo`, `EloChange` | Starting rating and final rating change |
| `startinghandcards` | `TableId`, `PlayerId`, `Card`, `Kept` | Every project card offered initially and whether it was bought |
| `gamecards` | `DrawType`, `DrawnGen`, `KeptGen`, `DraftedGen`, `BoughtGen`, `PlayedGen` | Card lifecycle and draft generation |

The public export is not a collection of raw replay logs. It contains enough derived card events to calculate Starting Hand and draft-generation results, but it does **not** retain rotating draft-pack pick position. Exact “first/second/third card picked from this pack” analysis needs raw replay JSON.

## TFMStats reference cohort

The locally reproduced old-site Starting Hand cohort is:

- `PlayerCount = 2`;
- Draft enabled;
- Colonies disabled;
- game mode is not `Friendly mode`;
- Prelude either on or off;
- every recorded map;
- no player or table Elo minimum.

This produces the same 215 card rows as the downloaded TFMStats snapshot. Its map composition is:

| Map | Games |
|---|---:|
| Tharsis | 108,578 |
| Hellas | 45,070 |
| Elysium | 17,257 |
| Vastitas Borealis | 15,016 |
| Amazonis Planitia | 893 |
| Random | 1 |

Four reference tables have inconsistent canonical player rows despite `gamestats.PlayerCount = 2`: one has three distinct players and three contain duplicated player rows. Therefore reports count games with distinct `TableId`; the website-compatible aggregations retain the exported player rows.

## Competitive app cohort

The default app cohort keeps the same base rules and adds:

- Prelude on;
- Tharsis, Hellas, Elysium, or Vastitas Borealis;
- average table Elo at least 450, calculated from the players' starting `Elo` values;
- every card retained; metrics with fewer than 100 observations are suppressed in the UI.

It contains 95,816 distinct games, 191,638 player-game rows, and 1,912,730 Starting Hand card offers. The map split is 49,273 Tharsis, 26,524 Hellas, 10,307 Elysium, and 9,712 Vastitas Borealis games.

The 450 rule is a **table average**, not “one player must be 450.” Thus 450 vs 450 qualifies and 500 vs 100 does not.

## Metrics

The reference page reported raw group averages:

`average Elo gain = mean(player EloChange for observations in the group)`

The current UI reports the raw group average:

`Average Elo Gain = mean(player EloChange for observations in the card group)`

No cohort baseline is subtracted in the interface. The API and generated analysis CSV also retain an optional zero-centered research metric:

`Elo delta = group average Elo gain − active cohort average Elo gain`

Combination metrics are computed for five kept-item pairings: corporation + prelude, corporation + project card, prelude + prelude, prelude + project card, and project card + project card. The default project-card population is cards bought in the initial hand (`startinghandcards.Kept = TRUE`). For card-containing modes, a generation replaces those cards with cards bought after that research draft (`KeptGen = DrawnGen`). It does not filter on `DraftedGen` alone or require `PlayedGen`. Rows are never removed for low volume, but Elo, win-rate, lift, and item baseline metrics are null below 100 player-game observations.

The competitive cohort baseline is currently about `+0.014`, so raw gain and the research delta are nearly identical for that cohort.

Keep rate is:

`100 × kept offers / all offers`

“Not kept” means the project card was offered but not bought. For later research generations, “kept” means `KeptGen = DrawnGen`; this comes from the all-player `cards_kept` event. The more literally named `BoughtGen` is only populated for a small legacy/player-perspective subset and is not suitable for aggregate analysis.

The UI keeps the full card row but suppresses an Offered, Kept, Not Kept Average Elo Gain, or Kept Win Rate when that particular group has fewer than 100 observations. The API and analysis CSV retain the underlying value and count.

The optional **Keep cards in view** control freezes the currently sorted card order and page during cohort changes, which supports side-by-side visual comparisons. It changes presentation only; it does not alter the query or statistics.

## Reproducible analysis

Run:

```bash
cd /home/pt/dev/mars-stats
.venv/bin/python analysis/cohort_analysis.py
```

This regenerates:

- `analysis/output/cohort_summary.csv` — definitions and sizes;
- `analysis/output/starting_hand_by_cohort.csv` — all 215 card aggregates for each reference/filter/map cohort;
- `analysis/output/map_contrasts.csv` — each map versus the other two maps, including approximate standard errors and z-scores;
- `analysis/output/REPORT.md` — readable largest-difference report.

The analysis deliberately adds filters one at a time: Prelude on, removal of Amazonis/Random, then the 450 average-table-Elo threshold. It also stores a three-map alternative and contrasts each of the four included maps against the other three. That prevents the final difference from being incorrectly attributed to a single filter.
