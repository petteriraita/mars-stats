# Terraforming Mars Statistics

A local statistics engine and interface for **Starting Hand** and **Project Card Combinations**. The browser talks only to the local server; DuckDB calculates every result from the downloaded TFMStats Parquet database.

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
- every card row retained; individual Elo cells with fewer than 10 observations suppressed.

These settings currently retain 95,816 games, 191,638 player-game rows, and 1.91 million starting-hand offers. They persist in the browser. Prelude is changed on Settings; the four maps and average-table-Elo range are selected directly above the Starting Hand table.

Map buttons are single-select by default: clicking a map immediately replaces the previous selection. **Select multiple** enables additive toggling, and **All maps** restores all four supported maps in one click. The selection is shared by Starting Hand and Combinations.

Available Elo ranges are All, 450+, 500+, and 600+.

Starting Hand reports offers, keep rate, and raw **Average Elo Gain** when bought, not bought, and offered. It is the mean final Elo change of the players in that card group; no cohort baseline is subtracted. Leaving Research Generation blank displays the initial Starting Hand; entering a generation displays locally calculated research-draft statistics, with “kept” meaning bought after the draft.

Every card remains in the table, but an Elo value based on fewer than 10 observations is displayed as `—`. This prevents a handful of results from appearing as a reliable extreme in smaller cohorts.

Enable **Keep cards in view** before changing a cohort to preserve the current page and card order while only the statistics update. Selecting a table sort unlocks the order. Draft Generation reloads immediately as soon as a number is typed.

Research-draft analysis uses `gamecards.DrawnGen` and `KeptGen` to calculate offered, bought, and not-bought metrics by generation. `KeptGen` comes from the all-player `cards_kept` event; the separate `BoughtGen` field is only populated for a small legacy/player-perspective subset. The public export does not retain rotating-pack pick position, so pick position is not shown. Exact pick-position analysis still requires raw replay JSON; the legacy importer in `stats_engine.py` remains available for that data.

Some exported `gamecards` rows contain parser artifacts (for example Undo controls, corporation/prelude names, unresolved `card_main_*` IDs, or whole-hand descriptions). Draft analysis accepts only names present in the clean 215-card Starting Hand project catalog, so these malformed rows are excluded.

Combinations uses the same Prelude, map, and average-table-Elo cohort. It mirrors the TFMStats modes: Corp + Prelude, Corp + Card, Prelude + Prelude, Prelude + Card, and Card + Card. With no generation entered, project cards are those actually bought in the initial hand (`startinghandcards.Kept = TRUE`). It reports raw Average Elo Gain, win rate, lift versus each item's individual baseline, and total lift. No row-count filter is applied; metrics for combinations with fewer than 20 games are displayed as `—` while the rows remain available. Types containing a project card can instead use cards bought after a specified research draft (`KeptGen = DrawnGen`). Neither mode requires the card to have been played (`PlayedGen`).

Starting Hand and Combinations card thumbnails and hover previews are stored locally under `assets/cards`. They can be refreshed with `.venv/bin/python download_card_images.py`; the source is the public [terraforming-mars/card-images](https://github.com/terraforming-mars/card-images) datastore.

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
