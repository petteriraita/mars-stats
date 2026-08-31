#!/usr/bin/env python3
"""Local DuckDB queries over the public TFMStats Parquet bundle."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import duckdb
except ModuleNotFoundError as error:  # pragma: no cover - exercised by the run-time error path.
    raise RuntimeError(
        "DuckDB is required for the Parquet dataset. Run the server with "
        "'/home/pt/dev/mars-stats/.venv/bin/python server.py'."
    ) from error


ROOT = Path(__file__).resolve().parent
DEFAULT_PARQUET_DIR = Path(
    os.environ.get("MARS_STATS_PARQUET_DIR", ROOT / "data" / "tfmstats_db")
).expanduser().resolve()

REQUIRED_TABLES = (
    "gamecards",
    "gameplayers_canonical",
    "games_canonical",
    "gamestats",
    "startinghandcards",
    "startinghandcorporations",
    "startinghandpreludes",
)

STANDARD_PROJECTS = ("City", "Greenery", "Aquifer", "Sell patents")
SUPPORTED_MAPS = (
    "Tharsis",
    "Hellas",
    "Elysium",
    "Vastitas Borealis",
)

COMBINATION_TYPES = {
    "corp-prelude": ("corp", "prelude"),
    "corp-card": ("corp", "card"),
    "prelude-prelude": ("prelude", "prelude"),
    "prelude-card": ("prelude", "card"),
    "card-card": ("card", "card"),
}
MINIMUM_COMBINATION_OBSERVATIONS = 20


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def parquet_path(directory: Path, table: str) -> str:
    return _sql_path(directory / f"{table}.parquet")


def available(directory: Path = DEFAULT_PARQUET_DIR) -> bool:
    return all((directory / f"{table}.parquet").is_file() for table in REQUIRED_TABLES)


def require_dataset(directory: Path = DEFAULT_PARQUET_DIR) -> None:
    missing = [f"{table}.parquet" for table in REQUIRED_TABLES if not (directory / f"{table}.parquet").is_file()]
    if missing:
        raise FileNotFoundError(
            f"TFMStats Parquet dataset is incomplete in {directory}: missing {', '.join(missing)}"
        )


def _normalized_card(column: str = "Card") -> str:
    # This is the same normalization currently used by the public TFMStats API.
    return f"CASE WHEN {column} = 'Power plant' THEN 'Power Plant' ELSE {column} END"


def _normalized_prelude(column: str = "Prelude") -> str:
    return (
        f"CASE WHEN {column} = 'Allied Bank' THEN 'Allied Banks' "
        f"WHEN {column} = 'Excentric Sponsor' THEN 'Eccentric Sponsor' "
        f"ELSE {column} END"
    )


def _eligible_players(
    directory: Path,
    *,
    prelude: bool | None = None,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> str:
    if maps:
        unknown = set(maps) - set(SUPPORTED_MAPS)
        if unknown:
            raise ValueError(f"Unknown map: {', '.join(sorted(unknown))}")
        map_values = ", ".join("'" + name.replace("'", "''") + "'" for name in maps)
        map_filter = f"AND g.Map IN ({map_values})"
    else:
        map_filter = ""
    if prelude is True:
        prelude_filter = "AND g.PreludeOn = TRUE"
    elif prelude is False:
        prelude_filter = "AND g.PreludeOn = FALSE"
    else:
        prelude_filter = ""
    min_average_elo = max(0, int(min_average_elo))
    max_average_elo = max(0, int(max_average_elo))
    if min_average_elo and max_average_elo and min_average_elo > max_average_elo:
        raise ValueError("Minimum average Elo cannot exceed maximum average Elo")
    if min_average_elo or max_average_elo:
        rating_join = f"""
        JOIN (
            SELECT TableId, avg(CAST(Elo AS DOUBLE)) AS AverageElo
            FROM read_parquet('{parquet_path(directory, "gameplayers_canonical")}')
            GROUP BY TableId
        ) table_rating ON table_rating.TableId = g.TableId
        """
        elo_filters = []
        if min_average_elo:
            elo_filters.append(f"table_rating.AverageElo >= {min_average_elo}")
        if max_average_elo:
            elo_filters.append(f"table_rating.AverageElo <= {max_average_elo}")
        elo_filter = "AND " + " AND ".join(elo_filters)
    else:
        rating_join = ""
        elo_filter = ""
    return f"""
        SELECT gp.TableId, gp.PlayerId,
               CAST(gp.EloChange AS DOUBLE) AS EloChange,
               gp.Position
        FROM read_parquet('{parquet_path(directory, "games_canonical")}') g
        JOIN read_parquet('{parquet_path(directory, "gameplayers_canonical")}') gp
          ON gp.TableId = g.TableId
        JOIN read_parquet('{parquet_path(directory, "gamestats")}') gs
          ON gs.TableId = g.TableId
        {rating_join}
        WHERE g.ColoniesOn = FALSE
          AND g.DraftOn = TRUE
          AND g.GameMode <> 'Friendly mode'
          AND gs.PlayerCount = 2
          {prelude_filter}
          {map_filter}
          {elo_filter}
    """


def _starting_offers(directory: Path) -> str:
    return f"""
        SELECT DISTINCT TableId, PlayerId, {_normalized_card()} AS Card, Kept
        FROM read_parquet('{parquet_path(directory, "startinghandcards")}')
    """


def _draft_offers(directory: Path) -> str:
    # The exported gamecards table retains draft generation and the card selected,
    # but not the position of a card within the rotating four-card pack. A small
    # number of parsed replays misclassify UI text, corporations, preludes, and
    # unresolved card IDs as draft cards. Starting-hand cards provide the clean
    # project-card catalog used to reject those malformed rows.
    return f"""
        SELECT DISTINCT gc.TableId, gc.PlayerId, {_normalized_card("gc.Card")} AS Card,
               gc.DrawnGen AS DraftNumber,
               gc.DraftedGen = gc.DrawnGen AS Kept
        FROM read_parquet('{parquet_path(directory, "gamecards")}') gc
        JOIN (
            SELECT DISTINCT {_normalized_card()} AS Card
            FROM read_parquet('{parquet_path(directory, "startinghandcards")}')
            WHERE Card IS NOT NULL AND trim(Card) <> ''
        ) valid_project
          ON valid_project.Card = {_normalized_card("gc.Card")}
        WHERE gc.DrawType = 'Draft' AND gc.DrawnGen IS NOT NULL
    """


def _rows(connection: duckdb.DuckDBPyConnection, sql: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, parameters or [])
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def starting_hand_stats(
    directory: Path = DEFAULT_PARQUET_DIR,
    stage: str = "starting_hand",
    draft_number: int | None = None,
    pick_number: int | None = None,
    *,
    prelude: bool | None = None,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> list[dict[str, Any]]:
    require_dataset(directory)
    if stage not in {"starting_hand", "draft"}:
        raise ValueError("stage must be starting_hand or draft")
    if pick_number is not None:
        raise ValueError("The public Parquet bundle does not retain draft pick position")

    if stage == "starting_hand":
        offers = _starting_offers(directory)
        extra_where = ""
        parameters: list[Any] = []
    else:
        offers = _draft_offers(directory)
        extra_where = "AND co.DraftNumber = ?" if draft_number is not None else ""
        parameters = [draft_number] if draft_number is not None else []

    query = f"""
        WITH all_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             card_offers AS ({offers})
        SELECT co.Card AS cardName,
               CAST(count(*) AS BIGINT) AS offeredGames,
               CAST(sum(CASE WHEN co.Kept = TRUE THEN 1 ELSE 0 END) AS BIGINT) AS keptGames,
               CAST(sum(CASE WHEN co.Kept IS DISTINCT FROM TRUE THEN 1 ELSE 0 END) AS BIGINT) AS notKeptGames,
               100.0 * sum(CASE WHEN co.Kept = TRUE THEN 1 ELSE 0 END) / nullif(count(*), 0) AS keepRate,
               avg(ap.EloChange) AS avgEloGainOffered,
               avg(CASE WHEN co.Kept = TRUE THEN ap.EloChange END) AS avgEloGainKept,
               avg(CASE WHEN co.Kept IS DISTINCT FROM TRUE THEN ap.EloChange END) AS avgEloGainNotKept,
               stddev_samp(ap.EloChange) AS stddevEloGainOffered,
               stddev_samp(CASE WHEN co.Kept = TRUE THEN ap.EloChange END) AS stddevEloGainKept,
               stddev_samp(CASE WHEN co.Kept IS DISTINCT FROM TRUE THEN ap.EloChange END) AS stddevEloGainNotKept,
               avg(ap.EloChange) - (SELECT avg(EloChange) FROM all_players) AS avgEloDeltaOffered,
               avg(CASE WHEN co.Kept = TRUE THEN ap.EloChange END)
                   - (SELECT avg(EloChange) FROM all_players) AS avgEloDeltaKept,
               avg(CASE WHEN co.Kept IS DISTINCT FROM TRUE THEN ap.EloChange END)
                   - (SELECT avg(EloChange) FROM all_players) AS avgEloDeltaNotKept,
               (SELECT avg(EloChange) FROM all_players) AS cohortAvgEloGain
        FROM card_offers co
        JOIN all_players ap ON ap.TableId = co.TableId AND ap.PlayerId = co.PlayerId
        WHERE co.Card NOT IN ('City', 'Greenery', 'Aquifer', 'Sell patents')
          {extra_where}
        GROUP BY co.Card
        ORDER BY avgEloGainOffered DESC, offeredGames DESC
    """
    with duckdb.connect() as connection:
        return _rows(connection, query, parameters)


def card_breakdown(
    directory: Path,
    card_name: str,
    *,
    prelude: bool | None = None,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> list[dict[str, Any]]:
    require_dataset(directory)
    query = f"""
        WITH all_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             starting AS ({_starting_offers(directory)}),
             drafts AS ({_draft_offers(directory)}),
             observations AS (
                 SELECT TableId, PlayerId, 'starting_hand' AS Stage, 0 AS DraftNumber, Kept
                 FROM starting WHERE Card = ?
                 UNION ALL
                 SELECT TableId, PlayerId, 'draft' AS Stage, DraftNumber, Kept
                 FROM drafts WHERE Card = ?
             )
        SELECT o.Stage AS stage, o.DraftNumber AS draftNumber, NULL::INTEGER AS pickNumber,
               CAST(count(*) AS BIGINT) AS offered,
               CAST(sum(CASE WHEN o.Kept = TRUE THEN 1 ELSE 0 END) AS BIGINT) AS kept,
               CAST(sum(CASE WHEN o.Kept IS DISTINCT FROM TRUE THEN 1 ELSE 0 END) AS BIGINT) AS notKept,
               100.0 * sum(CASE WHEN o.Kept = TRUE THEN 1 ELSE 0 END) / nullif(count(*), 0) AS keepRate,
               avg(ap.EloChange) AS eloOffered,
               avg(CASE WHEN o.Kept = TRUE THEN ap.EloChange END) AS eloKept,
               avg(CASE WHEN o.Kept IS DISTINCT FROM TRUE THEN ap.EloChange END) AS eloNotKept,
               avg(ap.EloChange) - (SELECT avg(EloChange) FROM all_players) AS eloDeltaOffered,
               avg(CASE WHEN o.Kept = TRUE THEN ap.EloChange END)
                   - (SELECT avg(EloChange) FROM all_players) AS eloDeltaKept,
               avg(CASE WHEN o.Kept IS DISTINCT FROM TRUE THEN ap.EloChange END)
                   - (SELECT avg(EloChange) FROM all_players) AS eloDeltaNotKept,
               (SELECT avg(EloChange) FROM all_players) AS cohortAvgEloGain
        FROM observations o
        JOIN all_players ap ON ap.TableId = o.TableId AND ap.PlayerId = o.PlayerId
        GROUP BY o.Stage, o.DraftNumber
        ORDER BY CASE o.Stage WHEN 'starting_hand' THEN 0 ELSE 1 END, o.DraftNumber
    """
    with duckdb.connect() as connection:
        return _rows(connection, query, [card_name, card_name])


def _combination_items(
    directory: Path,
    kind: str,
    *,
    stage: str,
    draft_number: int | None,
) -> str:
    if kind == "corp":
        return f"""
            SELECT DISTINCT TableId, PlayerId, Corporation AS Name
            FROM read_parquet('{parquet_path(directory, "startinghandcorporations")}')
            WHERE Kept = TRUE AND Corporation IS NOT NULL AND trim(Corporation) <> ''
        """
    if kind == "prelude":
        return f"""
            SELECT DISTINCT TableId, PlayerId, {_normalized_prelude()} AS Name
            FROM read_parquet('{parquet_path(directory, "startinghandpreludes")}')
            WHERE Kept = TRUE AND Prelude IS NOT NULL AND trim(Prelude) <> ''
              AND NOT regexp_matches(Prelude, '^card_prelude_', 'i')
        """
    if kind != "card":
        raise ValueError(f"Unknown combination item kind: {kind}")
    if stage == "starting_hand":
        return f"""
            SELECT DISTINCT TableId, PlayerId, Card AS Name
            FROM ({_starting_offers(directory)})
            WHERE Kept = TRUE
              AND Card NOT IN ('City', 'Greenery', 'Aquifer', 'Sell patents')
        """
    generation_filter = f"AND DraftNumber = {int(draft_number)}" if draft_number is not None else ""
    return f"""
        SELECT DISTINCT TableId, PlayerId, Card AS Name
        FROM ({_draft_offers(directory)})
        WHERE Kept = TRUE {generation_filter}
    """


def combination_stats(
    directory: Path = DEFAULT_PARQUET_DIR,
    *,
    combination_type: str = "card-card",
    stage: str = "starting_hand",
    draft_number: int | None = None,
    prelude: bool | None = True,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> list[dict[str, Any]]:
    """Return locally calculated starting-item combinations and baseline lifts."""
    require_dataset(directory)
    if combination_type not in COMBINATION_TYPES:
        raise ValueError(f"Unknown combination type: {combination_type}")
    if stage not in {"starting_hand", "draft"}:
        raise ValueError("stage must be starting_hand or draft")
    if draft_number is not None and draft_number < 1:
        raise ValueError("draft_number must be at least 1")
    first_kind, second_kind = COMBINATION_TYPES[combination_type]
    first_items = _combination_items(
        directory, first_kind, stage=stage, draft_number=draft_number
    )
    second_items = _combination_items(
        directory, second_kind, stage=stage, draft_number=draft_number
    )
    same_kind_filter = "AND i1.Name < i2.Name" if first_kind == second_kind else ""

    # A generation-specific card view compares every item inside the population
    # that actually reached and produced a selected card in that generation.
    uses_draft_cards = stage == "draft" and "card" in (first_kind, second_kind)
    if uses_draft_cards:
        card_items = _combination_items(
            directory, "card", stage=stage, draft_number=draft_number
        )
        active_players = f"""
            SELECT DISTINCT ep.*
            FROM eligible_players ep
            JOIN (SELECT DISTINCT TableId, PlayerId FROM ({card_items})) observed
              USING (TableId, PlayerId)
        """
    else:
        active_players = "SELECT DISTINCT * FROM eligible_players"

    query = f"""
        WITH eligible_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             active_players AS ({active_players}),
             first_items AS ({first_items}),
             second_items AS ({second_items}),
             first_baselines AS (
                 SELECT i.Name,
                        count(*) AS gameCount,
                        CASE WHEN count(*) >= {MINIMUM_COMBINATION_OBSERVATIONS} THEN avg(ap.EloChange) END AS avgEloChange,
                        CASE WHEN count(*) >= {MINIMUM_COMBINATION_OBSERVATIONS} THEN avg(CASE WHEN ap.Position = 1 THEN 1.0 ELSE 0.0 END) END AS winRate
                 FROM first_items i
                 JOIN active_players ap USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             second_baselines AS (
                 SELECT i.Name,
                        count(*) AS gameCount,
                        CASE WHEN count(*) >= {MINIMUM_COMBINATION_OBSERVATIONS} THEN avg(ap.EloChange) END AS avgEloChange,
                        CASE WHEN count(*) >= {MINIMUM_COMBINATION_OBSERVATIONS} THEN avg(CASE WHEN ap.Position = 1 THEN 1.0 ELSE 0.0 END) END AS winRate
                 FROM second_items i
                 JOIN active_players ap USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             combo_values AS (
                 SELECT i1.Name AS name1, i2.Name AS name2,
                        count(*) AS gameCount,
                        CASE WHEN count(*) >= {MINIMUM_COMBINATION_OBSERVATIONS} THEN avg(ap.EloChange) END AS avgEloChange,
                        CASE WHEN count(*) >= {MINIMUM_COMBINATION_OBSERVATIONS} THEN avg(CASE WHEN ap.Position = 1 THEN 1.0 ELSE 0.0 END) END AS winRate
                 FROM first_items i1
                 JOIN second_items i2 USING (TableId, PlayerId)
                 JOIN active_players ap ON ap.TableId = i1.TableId AND ap.PlayerId = i1.PlayerId
                 WHERE 1 = 1 {same_kind_filter}
                 GROUP BY i1.Name, i2.Name
             )
        SELECT c.name1, c.name2,
               CAST(c.gameCount AS BIGINT) AS gameCount,
               c.avgEloChange, c.winRate,
               b1.avgEloChange AS baseline1Elo,
               b2.avgEloChange AS baseline2Elo,
               CAST(b1.gameCount AS BIGINT) AS baseline1Games,
               CAST(b2.gameCount AS BIGINT) AS baseline2Games,
               CASE WHEN c.avgEloChange IS NOT NULL AND b1.avgEloChange IS NOT NULL
                    THEN c.avgEloChange - b1.avgEloChange END AS lift1,
               CASE WHEN c.avgEloChange IS NOT NULL AND b2.avgEloChange IS NOT NULL
                    THEN c.avgEloChange - b2.avgEloChange END AS lift2,
               CASE WHEN c.avgEloChange IS NOT NULL
                          AND b1.avgEloChange IS NOT NULL AND b2.avgEloChange IS NOT NULL
                    THEN c.avgEloChange - b1.avgEloChange - b2.avgEloChange END AS totalLift
        FROM combo_values c
        JOIN first_baselines b1 ON b1.Name = c.name1
        JOIN second_baselines b2 ON b2.Name = c.name2
        ORDER BY totalLift DESC NULLS LAST, c.gameCount DESC, c.name1, c.name2
    """
    with duckdb.connect() as connection:
        return _rows(connection, query)


def status(
    directory: Path = DEFAULT_PARQUET_DIR,
    *,
    prelude: bool | None = None,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> dict[str, Any]:
    require_dataset(directory)
    query = f"""
        WITH all_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             offers AS ({_starting_offers(directory)})
        SELECT (SELECT count(*) FROM all_players) AS games,
               (SELECT count(DISTINCT TableId) FROM all_players) AS gameCount,
               (SELECT avg(EloChange) FROM all_players) AS cohortAvgEloGain,
               (SELECT count(*) FROM offers o JOIN all_players ap USING (TableId, PlayerId)
                WHERE o.Card NOT IN ('City', 'Greenery', 'Aquifer', 'Sell patents')) AS offers,
               (SELECT count(DISTINCT o.Card) FROM offers o JOIN all_players ap USING (TableId, PlayerId)
                WHERE o.Card NOT IN ('City', 'Greenery', 'Aquifer', 'Sell patents')) AS cards
    """
    with duckdb.connect() as connection:
        summary = _rows(connection, query)[0]
    files = list(directory.glob("*.parquet"))
    updated = max((path.stat().st_mtime for path in files), default=0)
    return {
        "database": str(directory),
        "dataset": "TFMStats public Parquet bundle",
        "games": summary["games"],
        "gameCount": summary["gameCount"],
        "offers": summary["offers"],
        "cards": summary["cards"],
        "updatedAt": datetime.fromtimestamp(updated, UTC).isoformat() if updated else None,
        "sourceDir": str(directory),
        "filesScanned": len(files),
        "recordsSeen": summary["offers"],
        "cohortAvgEloGain": summary["cohortAvgEloGain"],
        "skippedCohort": 0,
        "skippedSchema": 0,
        "supportsPickPosition": False,
        "cohort": {
            "prelude": "on" if prelude is True else "off" if prelude is False else "either",
            "maps": list(maps or []),
            "minAverageElo": max(0, int(min_average_elo)),
            "maxAverageElo": max(0, int(max_average_elo)),
        },
        "stages": ["starting_hand", "draft_generation"],
    }
