# Terraforming Mars Statistics

A local statistics engine and interface for **Drafting** and project-card play decisions. The browser talks only to the local server; DuckDB calculates every result from the downloaded TFMStats Parquet database.

## Run

```bash
cd /home/pt/dev/mars-stats
.venv/bin/python server.py
```

Open <http://localhost:8080>.

## Deploy

The repository includes a Render Blueprint. Deploy it with the one-click link:

<https://render.com/deploy?repo=https://github.com/petteriraita/mars-stats>

Render downloads the public Parquet bundle during the build and starts the Python API server. The free service is suitable for a small demo; it may sleep after inactivity and wake with a short delay.

## Local data

The public database bundle is already downloaded and extracted:

- archive: `data/tfmstats_db.zip` — about 364 MiB;
- extracted Parquet: `data/tfmstats_db/` — about 364 MiB;
- 18 tables, including 248,813 games and 59.3 million game-card rows.

Refresh it from the anonymous public endpoint—no API key or BGA password is needed:

```bash
cd /home/pt/dev/mars-stats
.venv/bin/python download_dataset.py --force
```

The source route is <https://api.tfmstats.com/api/download-db>. Queries run against the local files after download; the app is not a wrapper around tfmstats.com.

## Calculations

The complete source schema, old-site cohort definition, competitive cohort, formulas, and known data limitations are recorded in [`docs/DATA_AND_COHORTS.md`](docs/DATA_AND_COHORTS.md).

The query engine can reproduce the official TFMStats Starting Hand cohort exactly:

- two players;
- Draft enabled;
- Colonies disabled;
- non-friendly game mode;
- both Prelude-on and Prelude-off games included.

The interface then applies competitive defaults chosen for this project:

- Prelude enabled;
- Tharsis, Hellas, Elysium, and Vastitas Borealis;
- Amazonis Planitia and Random rejected by the API;
- minimum 450 average table Elo, calculated across both players;
- every card row retained; individual Average Elo and Win Rate cells with fewer than 100 observations suppressed.

These settings currently retain 95,816 games and 191,638 player-game rows. They persist in the browser. Prelude is changed on Settings; the four maps and average-table-Elo range are selected directly above the Drafting table.

Map buttons are single-select by default: clicking a map immediately replaces the previous selection. **Select multiple** enables additive toggling, and **All maps** restores all four supported maps in one click.

The browser remembers the active page, draft generation, searches, rows per page, pagination, sorting, analysis type, and selected card across reloads. Clicking a project card opens an all-generation detail table; it shows bought/not-bought results in Draft buying mode and played/not-played results in Play decisions mode. Card previews close on click/tap, scrolling, resizing, page changes, window blur, or Escape.

Available Elo ranges are All, 450+, 500+, and 600+.

Every draft row remains in the table, but an Average Elo or Win Rate value below the selected observation threshold is displayed as `—`. This prevents a handful of results from appearing as a reliable extreme in smaller cohorts. Draft Generation reloads immediately as soon as a number is typed.

Research-draft analysis uses `gamecards.DraftedGen` for cards positively identified as a player's active selections during the rotating draft and `KeptGen` for the subset bought afterward. The automatically received fourth card is usually not attributable in the public export and is therefore missing non-randomly.

Some exported `gamecards` rows contain parser artifacts (for example Undo controls, corporation/prelude names, unresolved `card_main_*` IDs, or whole-hand descriptions). Draft analysis accepts only names present in the clean 215-card Starting Hand project catalog, so these malformed rows are excluded.

Drafting uses the same Prelude, map, and average-table-Elo cohort. Leave Draft generation empty to return to Starting Hand. Generation 2 is the first normal four-card research draft, generation 3 is the second, and so on. Generation-1 rows are excluded because source-log sampling shows that they contain opening setup and card-effect acquisitions rather than the first research draft. Other card-effect draws are also excluded. The page can rank cards directly or condition them on a corporation, prelude, or another drafted card. “Drafted Games” means the card is positively identified as one of the player's active draft selections; “Bought” means it was then present in `cards_kept`. It reports Average Elo Gain, win rate, bought/not-bought comparisons, and pair lifts. For Corp + Card, the optional corporation adjustment subtracts that corporation's cohort-wide average Elo gain from both bought/not-bought or played/not-played values. No row-count filter is applied; metrics below the selected reliability threshold are displayed as `—` while rows remain available.

The **Gen 1 Production** navigation page estimates MC, steel, titanium, energy, heat, and plant production plus Earth, Space, Jovian, and Science tag values from 26 auditable anchor cards. For each card it compares Gen-1 players with the same corporation who did and did not play that card, calibrates Elo per MC of efficiency, then uses non-negative weighted least squares for interpretable values. Card costs, production, tags, VP assumptions, and model notes live in `data/gen1_production_cards.json` rather than being embedded in queries. These are strategic associations from card-play decisions, not guaranteed causal prices.

Corp + Card defaults to draft-buying metrics. Its optional **Play decisions** tab replaces those columns with card availability, played rate, played/not-played Elo, and played win rate. It defaults to one aggregated row per card; entering a Corporation search switches it to corporation-conditioned rows. There is no separate Played page.

Drafting card thumbnails and hover previews are stored locally under `assets/cards`. They can be refreshed with `.venv/bin/python download_card_images.py`; the source is the public [terraforming-mars/card-images](https://github.com/terraforming-mars/card-images) datastore.

## Install from scratch

DuckDB currently has a wheel for Python 3.13, while this machine's system Python is 3.14:

```bash
cd /home/pt/dev/mars-stats
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python download_dataset.py
```

## Validate

```bash
.venv/bin/python -B -m unittest discover -s tests -v
node --check app.js
node tests/test_app.js
```

The local snapshot has also been compared field-for-field with the live public API: all 215 Starting Hand rows and all 14,693 card-card combination rows match.

## Cohort analysis

Regenerate the filtered/unfiltered card datasets and comparison report:

```bash
.venv/bin/python analysis/cohort_analysis.py
```

See [`analysis/output/REPORT.md`](analysis/output/REPORT.md). The accompanying CSV files retain every cohort/card aggregate for direct DuckDB, spreadsheet, or Python analysis without copying the raw Parquet database.
