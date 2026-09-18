#!/usr/bin/env python3
"""Local DuckDB queries over the public TFMStats Parquet bundle."""

from __future__ import annotations

import json
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
MINIMUM_METRIC_OBSERVATIONS = 100
MINIMUM_COMBINATION_OBSERVATIONS = MINIMUM_METRIC_OBSERVATIONS
GEN1_PRODUCTION_METADATA = ROOT / "data" / "gen1_production_cards.json"


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
    # DraftedGen identifies cards actively selected during the rotating draft.
    # KeptGen identifies which selected cards the player then bought. The automatic
    # fourth card is usually not attributable in the public export, so it is absent
    # from this analysis unless a newer parser explicitly reconstructed it.
    # Generation-1 rows are excluded because source-log sampling shows that they are
    # opening setup and card-effect acquisitions, not the first research draft.
    #
    # Starting-hand cards provide the clean project-card catalog used to reject
    # UI text, corporations, preludes, and unresolved card IDs misparsed as cards.
    return f"""
        SELECT DISTINCT gc.TableId, gc.PlayerId, {_normalized_card("gc.Card")} AS Card,
               gc.DraftedGen AS DraftNumber,
               COALESCE(gc.KeptGen = gc.DraftedGen, FALSE) AS Kept
        FROM read_parquet('{parquet_path(directory, "gamecards")}') gc
        JOIN (
            SELECT DISTINCT {_normalized_card()} AS Card
            FROM read_parquet('{parquet_path(directory, "startinghandcards")}')
            WHERE Card IS NOT NULL AND trim(Card) <> ''
        ) valid_project
          ON valid_project.Card = {_normalized_card("gc.Card")}
        WHERE gc.DrawType = 'Draft' AND gc.DraftedGen >= 2
    """


def _rows(connection: duckdb.DuckDBPyConnection, sql: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, parameters or [])
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _smooth_display_metrics(
    centre: list[dict[str, Any]],
    neighbors: list[list[dict[str, Any]]],
    *,
    key: tuple[str, ...],
    metrics: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Blend display metrics only; counts stay tied to the selected decision point.

    The selected generation gets 60% weight and each adjacent generation 20%.
    At either edge, the available neighbour is renormalized to 25%.
    """
    indexes = [{tuple(row[name] for name in key): row for row in group} for group in neighbors]
    result: list[dict[str, Any]] = []
    for row in centre:
        item = dict(row)
        item_key = tuple(row[name] for name in key)
        sources = [(0.6, row)] + [(0.2, index[item_key]) for index in indexes if item_key in index]
        for metric in metrics:
            usable = [(weight, source[metric]) for weight, source in sources if source.get(metric) is not None]
            if usable:
                total_weight = sum(weight for weight, _ in usable)
                item[metric] = sum(weight * float(value) for weight, value in usable) / total_weight
        result.append(item)
    return result


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
    smooth: bool = False,
) -> list[dict[str, Any]]:
    require_dataset(directory)
    if stage not in {"starting_hand", "draft"}:
        raise ValueError("stage must be starting_hand or draft")
    if pick_number is not None:
        raise ValueError("The public Parquet bundle does not retain draft pick position")

    if smooth:
        center = starting_hand_stats(
            directory, stage, draft_number, pick_number, prelude=prelude, maps=maps,
            min_average_elo=min_average_elo, max_average_elo=max_average_elo, smooth=False,
        )
        adjacent: list[list[dict[str, Any]]] = []
        if stage == "starting_hand":
            adjacent.append(starting_hand_stats(
                directory, "draft", 2, None, prelude=prelude, maps=maps,
                min_average_elo=min_average_elo, max_average_elo=max_average_elo, smooth=False,
            ))
        elif draft_number is not None:
            if draft_number > 2:
                adjacent.append(starting_hand_stats(
                    directory, "draft", draft_number - 1, None, prelude=prelude, maps=maps,
                    min_average_elo=min_average_elo, max_average_elo=max_average_elo, smooth=False,
                ))
            adjacent.append(starting_hand_stats(
                directory, "draft", draft_number + 1, None, prelude=prelude, maps=maps,
                min_average_elo=min_average_elo, max_average_elo=max_average_elo, smooth=False,
            ))
        return _smooth_display_metrics(
            center, adjacent, key=("cardName",), metrics=(
                "keepRate", "winRateKept", "avgEloGainOffered", "avgEloGainKept",
                "avgEloGainNotKept", "avgEloDeltaOffered", "avgEloDeltaKept", "avgEloDeltaNotKept",
            ),
        )

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
               100.0 * avg(CASE WHEN co.Kept = TRUE AND ap.Position = 1 THEN 1.0 WHEN co.Kept = TRUE THEN 0.0 END) AS winRateKept,
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
    corporation: str | None = None,
) -> list[dict[str, Any]]:
    require_dataset(directory)
    if corporation:
        corporation_literal = "'" + corporation.replace("'", "''") + "'"
        corporation_ctes = f""",
             corporations AS ({_combination_items(directory, "corp", stage="starting_hand", draft_number=None)}),
             corporation_baseline AS (
                 SELECT avg(ap.EloChange) AS value
                 FROM corporations c JOIN all_players ap USING (TableId, PlayerId)
                 WHERE c.Name = {corporation_literal}
             )"""
        corporation_join = "JOIN corporations c ON c.TableId = o.TableId AND c.PlayerId = o.PlayerId"
        corporation_where = f"WHERE c.Name = {corporation_literal}"
        corporation_baseline = "(SELECT value FROM corporation_baseline)"
    else:
        corporation_ctes = ""
        corporation_join = ""
        corporation_where = ""
        corporation_baseline = "NULL::DOUBLE"
    query = f"""
        WITH all_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             starting AS ({_starting_offers(directory)}),
             drafts AS ({_draft_offers(directory)})
             {corporation_ctes},
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
               avg(CASE WHEN o.Kept = TRUE AND ap.Position = 1 THEN 1.0 WHEN o.Kept = TRUE THEN 0.0 END) AS winRateKept,
               avg(CASE WHEN o.Kept IS DISTINCT FROM TRUE AND ap.Position = 1 THEN 1.0 WHEN o.Kept IS DISTINCT FROM TRUE THEN 0.0 END) AS winRateNotKept,
               avg(ap.EloChange) - (SELECT avg(EloChange) FROM all_players) AS eloDeltaOffered,
               avg(CASE WHEN o.Kept = TRUE THEN ap.EloChange END)
                   - (SELECT avg(EloChange) FROM all_players) AS eloDeltaKept,
               avg(CASE WHEN o.Kept IS DISTINCT FROM TRUE THEN ap.EloChange END)
                   - (SELECT avg(EloChange) FROM all_players) AS eloDeltaNotKept,
               (SELECT avg(EloChange) FROM all_players) AS cohortAvgEloGain,
               {corporation_baseline} AS corporationBaselineElo
        FROM observations o
        JOIN all_players ap ON ap.TableId = o.TableId AND ap.PlayerId = o.PlayerId
        {corporation_join}
        {corporation_where}
        GROUP BY o.Stage, o.DraftNumber
        ORDER BY CASE o.Stage WHEN 'starting_hand' THEN 0 ELSE 1 END, o.DraftNumber
    """
    with duckdb.connect() as connection:
        return _rows(connection, query, [card_name, card_name])


def played_card_breakdown(
    directory: Path,
    card_name: str,
    *,
    prelude: bool | None = True,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
    corporation: str | None = None,
) -> list[dict[str, Any]]:
    """Return every generation's play-or-hold result for one bought card."""
    require_dataset(directory)
    if corporation:
        corporation_literal = "'" + corporation.replace("'", "''") + "'"
        corporation_ctes = f""",
             corporations AS ({_combination_items(directory, "corp", stage="starting_hand", draft_number=None)}),
             corporation_baseline AS (
                 SELECT avg(ap.EloChange) AS value
                 FROM corporations c JOIN eligible_players ap USING (TableId, PlayerId)
                 WHERE c.Name = {corporation_literal}
             )"""
        corporation_join = "JOIN corporations c ON c.TableId = o.TableId AND c.PlayerId = o.PlayerId"
        corporation_where = f"WHERE c.Name = {corporation_literal}"
        corporation_baseline = "(SELECT value FROM corporation_baseline)"
    else:
        corporation_ctes = ""
        corporation_join = ""
        corporation_where = ""
        corporation_baseline = "NULL::DOUBLE"
    query = f"""
        WITH eligible_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             generations AS (SELECT generation FROM range(1, 15) AS t(generation))
             {corporation_ctes},
             card_records AS (
                 SELECT DISTINCT gc.TableId, gc.PlayerId, gc.KeptGen, gc.PlayedGen
                 FROM read_parquet('{parquet_path(directory, "gamecards")}') gc
                 WHERE {_normalized_card('gc.Card')} = ?
             ),
             observations AS (
                 SELECT g.generation, c.TableId, c.PlayerId,
                        c.PlayedGen = g.generation AS Played
                 FROM card_records c
                 CROSS JOIN generations g
                 WHERE c.KeptGen <= g.generation
                   AND (c.PlayedGen IS NULL OR c.PlayedGen >= g.generation)
             )
        SELECT o.generation,
               CAST(count(*) AS BIGINT) AS available,
               CAST(sum(CASE WHEN o.Played THEN 1 ELSE 0 END) AS BIGINT) AS played,
               CAST(sum(CASE WHEN o.Played IS DISTINCT FROM TRUE THEN 1 ELSE 0 END) AS BIGINT) AS notPlayed,
               1.0 * sum(CASE WHEN o.Played THEN 1 ELSE 0 END) / NULLIF(count(*), 0) AS playRate,
               avg(ap.EloChange) AS eloAvailable,
               avg(CASE WHEN o.Played THEN ap.EloChange END) AS eloPlayed,
               avg(CASE WHEN o.Played IS DISTINCT FROM TRUE THEN ap.EloChange END) AS eloNotPlayed,
               avg(CASE WHEN o.Played AND ap.Position = 1 THEN 1.0 WHEN o.Played THEN 0.0 END) AS winRatePlayed,
               avg(CASE WHEN o.Played IS DISTINCT FROM TRUE AND ap.Position = 1 THEN 1.0 WHEN o.Played IS DISTINCT FROM TRUE THEN 0.0 END) AS winRateNotPlayed,
               {corporation_baseline} AS corporationBaselineElo
        FROM observations o
        JOIN eligible_players ap USING (TableId, PlayerId)
        {corporation_join}
        {corporation_where}
        GROUP BY o.generation
        ORDER BY o.generation
    """
    with duckdb.connect() as connection:
        return _rows(connection, query, [card_name])


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


def _combination_not_kept_items(
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
            WHERE Kept IS DISTINCT FROM TRUE
              AND Corporation IS NOT NULL AND trim(Corporation) <> ''
        """
    if kind == "prelude":
        return f"""
            SELECT DISTINCT TableId, PlayerId, {_normalized_prelude()} AS Name
            FROM read_parquet('{parquet_path(directory, "startinghandpreludes")}')
            WHERE Kept IS DISTINCT FROM TRUE
              AND Prelude IS NOT NULL AND trim(Prelude) <> ''
              AND NOT regexp_matches(Prelude, '^card_prelude_', 'i')
        """
    if kind != "card":
        return "SELECT NULL::INTEGER AS TableId, NULL::INTEGER AS PlayerId, NULL::VARCHAR AS Name WHERE FALSE"
    if stage == "starting_hand":
        return f"""
            SELECT DISTINCT TableId, PlayerId, Card AS Name
            FROM ({_starting_offers(directory)})
            WHERE Kept IS DISTINCT FROM TRUE
              AND Card NOT IN ('City', 'Greenery', 'Aquifer', 'Sell patents')
        """
    generation_filter = f"AND DraftNumber = {int(draft_number)}" if draft_number is not None else ""
    return f"""
        SELECT DISTINCT TableId, PlayerId, Card AS Name
        FROM ({_draft_offers(directory)})
        WHERE Kept IS DISTINCT FROM TRUE {generation_filter}
    """


def _combination_offered_items(
    directory: Path,
    kind: str,
    *,
    stage: str,
    draft_number: int | None,
) -> str:
    """Items available to a player, rather than only the items they bought."""
    if kind == "prelude":
        return f"""
            SELECT DISTINCT TableId, PlayerId, {_normalized_prelude()} AS Name
            FROM read_parquet('{parquet_path(directory, "startinghandpreludes")}')
            WHERE Prelude IS NOT NULL AND trim(Prelude) <> ''
              AND NOT regexp_matches(Prelude, '^card_prelude_', 'i')
        """
    if kind != "card":
        return _combination_items(directory, kind, stage=stage, draft_number=draft_number)
    if stage == "starting_hand":
        return f"""
            SELECT DISTINCT TableId, PlayerId, Card AS Name
            FROM ({_starting_offers(directory)})
            WHERE Card NOT IN ('City', 'Greenery', 'Aquifer', 'Sell patents')
        """
    generation_filter = f"AND DraftNumber = {int(draft_number)}" if draft_number is not None else ""
    return f"""
        SELECT DISTINCT TableId, PlayerId, Card AS Name
        FROM ({_draft_offers(directory)})
        WHERE 1 = 1 {generation_filter}
    """


def item_stats(
    directory: Path = DEFAULT_PARQUET_DIR,
    *,
    kind: str,
    prelude: bool | None = True,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> list[dict[str, Any]]:
    """Return standalone bought corporations or preludes for the active cohort."""
    if kind not in {"corp", "prelude"}:
        raise ValueError("Standalone statistics support corporations or preludes")
    require_dataset(directory)
    kept_items = _combination_items(directory, kind, stage="starting_hand", draft_number=None)
    offered_items = (f"""
        SELECT DISTINCT TableId, PlayerId, Corporation AS Name
        FROM read_parquet('{parquet_path(directory, "startinghandcorporations")}')
        WHERE Corporation IS NOT NULL AND trim(Corporation) <> ''
    """ if kind == "corp" else _combination_offered_items(
        directory, kind, stage="starting_hand", draft_number=None
    ))
    not_kept_items = _combination_not_kept_items(directory, kind, stage="starting_hand", draft_number=None)
    query = f"""
        WITH eligible_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             kept_items AS ({kept_items}),
             offered_items AS ({offered_items}),
             not_kept_items AS ({not_kept_items}),
             kept_values AS (
                 SELECT i.Name, count(*) AS gameCount, avg(ep.EloChange) AS avgEloChange,
                        avg(CASE WHEN ep.Position = 1 THEN 1.0 ELSE 0.0 END) AS winRate
                 FROM kept_items i JOIN eligible_players ep USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             offered_values AS (
                 SELECT i.Name, count(*) AS gameCount
                 FROM offered_items i JOIN eligible_players ep USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             not_kept_values AS (
                 SELECT i.Name, count(*) AS gameCount, avg(ep.EloChange) AS avgEloChange
                 FROM not_kept_items i JOIN eligible_players ep USING (TableId, PlayerId)
                 GROUP BY i.Name
             )
        SELECT o.Name AS name,
               CAST(COALESCE(k.gameCount, 0) AS BIGINT) AS gameCount,
               CAST(o.gameCount AS BIGINT) AS offeredGames,
               1.0 * COALESCE(k.gameCount, 0) / NULLIF(o.gameCount, 0) AS keepRate,
               k.avgEloChange, k.winRate,
               CAST(COALESCE(n.gameCount, 0) AS BIGINT) AS notKeptGames,
               n.avgEloChange AS avgEloNotKept
        FROM offered_values o
        LEFT JOIN kept_values k ON k.Name = o.Name
        LEFT JOIN not_kept_values n ON n.Name = o.Name
        ORDER BY k.avgEloChange DESC NULLS LAST, o.gameCount DESC, o.Name
    """
    with duckdb.connect() as connection:
        return _rows(connection, query)


def played_card_stats(
    directory: Path = DEFAULT_PARQUET_DIR,
    *,
    generation: int,
    prelude: bool | None = True,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> list[dict[str, Any]]:
    """Compare available cards played this generation with cards held past it.

    An observation is a project card bought in or before ``generation`` that had
    not already been played in an earlier generation. The public export has no
    discarded/sold generation, so this is an approximation of the in-hand
    decision set rather than a guarantee that every unplayed card was retained.
    """
    require_dataset(directory)
    if generation < 1 or generation > 14:
        raise ValueError("generation must be between 1 and 14")
    corporations = _combination_items(directory, "corp", stage="starting_hand", draft_number=None)
    query = f"""
        WITH eligible_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             corporations AS ({corporations}),
             corporation_baselines AS (
                 SELECT c.Name, avg(ep.EloChange) AS avgEloChange
                 FROM corporations c
                 JOIN eligible_players ep USING (TableId, PlayerId)
                 GROUP BY c.Name
             ),
             valid_project_cards AS (
                 SELECT DISTINCT {_normalized_card()} AS Card
                 FROM read_parquet('{parquet_path(directory, "startinghandcards")}')
                 WHERE Card IS NOT NULL AND trim(Card) <> ''
             ),
             available_cards AS (
                 SELECT gc.TableId, gc.PlayerId, {_normalized_card('gc.Card')} AS Card,
                        gc.PlayedGen = {int(generation)} AS Played
                 FROM read_parquet('{parquet_path(directory, "gamecards")}') gc
                 JOIN valid_project_cards valid ON valid.Card = {_normalized_card('gc.Card')}
                 WHERE gc.KeptGen <= {int(generation)}
                   AND (gc.PlayedGen IS NULL OR gc.PlayedGen >= {int(generation)})
                   AND gc.Card NOT IN ('City', 'Greenery', 'Aquifer', 'Sell patents')
             )
        SELECT c.Name AS corporation, b.Card AS card,
               CAST(count(*) AS BIGINT) AS acquiredGames,
               CAST(sum(CASE WHEN b.Played THEN 1 ELSE 0 END) AS BIGINT) AS playedGames,
               CAST(sum(CASE WHEN b.Played IS DISTINCT FROM TRUE THEN 1 ELSE 0 END) AS BIGINT) AS notPlayedGames,
               1.0 * sum(CASE WHEN b.Played THEN 1 ELSE 0 END) / NULLIF(count(*), 0) AS playRate,
               avg(CASE WHEN b.Played THEN ep.EloChange END) AS avgEloPlayed,
               avg(CASE WHEN b.Played IS DISTINCT FROM TRUE THEN ep.EloChange END) AS avgEloNotPlayed,
               avg(CASE WHEN b.Played AND ep.Position = 1 THEN 1.0 WHEN b.Played THEN 0.0 END) AS winRatePlayed,
               max(cb.avgEloChange) AS corporationBaselineElo
        FROM corporations c
        JOIN available_cards b USING (TableId, PlayerId)
        JOIN eligible_players ep USING (TableId, PlayerId)
        JOIN corporation_baselines cb ON cb.Name = c.Name
        GROUP BY c.Name, b.Card
        ORDER BY avgEloPlayed DESC NULLS LAST, acquiredGames DESC, c.Name, b.Card
    """
    with duckdb.connect() as connection:
        return _rows(connection, query)


def gen1_mc_production_analysis(
    directory: Path = DEFAULT_PARQUET_DIR,
    *,
    prelude: bool | None = True,
    maps: tuple[str, ...] | list[str] | None = None,
    min_average_elo: int = 0,
    max_average_elo: int = 0,
) -> dict[str, Any]:
    """Fit the Gen-1 value of MC production from corporation-stratified play deltas."""
    require_dataset(directory)
    metadata = json.loads(GEN1_PRODUCTION_METADATA.read_text(encoding="utf-8"))
    cards = metadata["cards"]
    assumptions = metadata["assumptions"]
    names_sql = ", ".join(
        "('" + card["name"].replace("'", "''") + "')" for card in cards
    )
    corporations = _combination_items(directory, "corp", stage="starting_hand", draft_number=None)
    query = f"""
        WITH eligible_players AS ({_eligible_players(directory, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo)}),
             corporations AS ({corporations}),
             population AS (
                 SELECT ep.TableId, ep.PlayerId, ep.EloChange, c.Name AS Corporation
                 FROM eligible_players ep
                 JOIN corporations c USING (TableId, PlayerId)
             ),
             model_cards(Card) AS (VALUES {names_sql}),
             played AS (
                 SELECT DISTINCT gc.TableId, gc.PlayerId, {_normalized_card('gc.Card')} AS Card
                 FROM read_parquet('{parquet_path(directory, "gamecards")}') gc
                 JOIN model_cards m ON m.Card = {_normalized_card('gc.Card')}
                 WHERE gc.PlayedGen = 1
             )
        SELECT m.Card AS card, p.Corporation AS corporation,
               CAST(count(*) FILTER (WHERE played.PlayerId IS NOT NULL) AS BIGINT) AS playedGames,
               avg(p.EloChange) FILTER (WHERE played.PlayerId IS NOT NULL) AS playedElo,
               CAST(count(*) FILTER (WHERE played.PlayerId IS NULL) AS BIGINT) AS baselineGames,
               avg(p.EloChange) FILTER (WHERE played.PlayerId IS NULL) AS baselineElo
        FROM population p
        CROSS JOIN model_cards m
        LEFT JOIN played
          ON played.TableId = p.TableId AND played.PlayerId = p.PlayerId AND played.Card = m.Card
        GROUP BY m.Card, p.Corporation
    """
    with duckdb.connect() as connection:
        strata = _rows(connection, query)

    by_name: dict[str, list[dict[str, Any]]] = {card["name"]: [] for card in cards}
    for row in strata:
        if row["playedGames"] and row["baselineGames"] and row["playedElo"] is not None and row["baselineElo"] is not None:
            by_name[row["card"]].append(row)

    results: list[dict[str, Any]] = []
    purchase_cost = float(assumptions["cardPurchaseCost"])
    vp_value = float(assumptions["victoryPointValueMc"])
    for card in cards:
        card_strata = by_name[card["name"]]
        played_games = sum(row["playedGames"] for row in card_strata)
        baseline_games = sum(row["baselineGames"] for row in card_strata)
        observed_delta = (
            sum((row["playedElo"] - row["baselineElo"]) * row["playedGames"] for row in card_strata)
            / played_games
        ) if played_games else None
        results.append({
            **card,
            "purchaseCost": purchase_cost,
            "totalCost": float(card["playCost"]) + purchase_cost,
            "immediateMc": float(card.get("immediateMc", 0)),
            "playedGames": played_games,
            "baselineGames": baseline_games,
            "observedEloDelta": observed_delta,
        })

    # Calibrate Elo/MC from the four reference MC-production anchors using the
    # reference's deliberately modest 1-MC tag and VP nuisance assumptions.
    s11 = s12 = s22 = t1 = t2 = 0.0
    for row in results:
        if row.get("anchor") != "mc" or row["observedEloDelta"] is None or not row["playedGames"]:
            continue
        weight = float(row["playedGames"])
        x1 = float(row["production"].get("mc", 0))
        x2 = float(len(row["tags"]) + row["expectedVictoryPoints"] - row["totalCost"])
        y = float(row["observedEloDelta"])
        s11 += weight * x1 * x1
        s12 += weight * x1 * x2
        s22 += weight * x2 * x2
        t1 += weight * x1 * y
        t2 += weight * x2 * y
    determinant = s11 * s22 - s12 * s12
    if abs(determinant) < 1e-12:
        raise RuntimeError("Insufficient independent MC-production anchors to fit the model")
    production_coefficient = (t1 * s22 - t2 * s12) / determinant
    elo_per_mc = (s11 * t2 - s12 * t1) / determinant

    production_names = ("mc", "steel", "titanium", "energy", "heat", "plant")
    estimated_tags = tuple(assumptions["estimatedTags"])
    feature_names = production_names + estimated_tags
    usable = [row for row in results if row["observedEloDelta"] is not None and row["playedGames"]]
    matrix = [
        [float(row["production"].get(name, 0)) if name in production_names else float(name in row["tags"])
         for name in feature_names]
        for row in usable
    ]
    targets = [
        row["totalCost"] - row["immediateMc"] - float(row["expectedVictoryPoints"]) * vp_value
        + float(row["observedEloDelta"]) / elo_per_mc
        for row in usable
    ]
    weights = [float(row["playedGames"]) for row in usable]

    # Non-negative coordinate descent keeps sparse, correlated tag estimates
    # interpretable instead of allowing one tag to become strongly negative.
    values = [1.0] * len(feature_names)
    for _ in range(500):
        largest_change = 0.0
        for column in range(len(feature_names)):
            numerator = denominator = 0.0
            for vector, target, weight in zip(matrix, targets, weights, strict=True):
                x = vector[column]
                if x == 0:
                    continue
                without_column = sum(value * coefficient for index, (value, coefficient) in enumerate(zip(vector, values, strict=True)) if index != column)
                numerator += weight * x * (target - without_column)
                denominator += weight * x * x
            updated = max(0.0, numerator / denominator) if denominator else 0.0
            largest_change = max(largest_change, abs(updated - values[column]))
            values[column] = updated
        if largest_change < 1e-8:
            break
    fitted_values = dict(zip(feature_names, values, strict=True))

    squared_error = total_weight = 0.0
    for row in results:
        production_value = sum(float(quantity) * fitted_values[name] for name, quantity in row["production"].items())
        tag_value = sum(fitted_values.get(tag, 0.0) for tag in row["tags"])
        fixed_value = row["immediateMc"] + float(row["expectedVictoryPoints"]) * vp_value + tag_value
        predicted = elo_per_mc * (production_value + fixed_value - row["totalCost"])
        row["productionValueMc"] = production_value
        row["tagValueMc"] = tag_value
        row["fixedValueMc"] = fixed_value
        row["predictedEloDelta"] = predicted
        row["modeledFairValueMc"] = production_value + fixed_value
        row["modeledEfficiencyMc"] = row["modeledFairValueMc"] - row["totalCost"]
        row["observedFairValueMc"] = (
            row["totalCost"] + row["observedEloDelta"] / elo_per_mc
            if row["observedEloDelta"] is not None else None
        )
        if row["observedEloDelta"] is not None:
            squared_error += row["playedGames"] * (row["observedEloDelta"] - predicted) ** 2
            total_weight += row["playedGames"]

    return {
        "resource": "Production and tags",
        "generation": 1,
        "mcProductionValue": fitted_values["mc"],
        "eloPerMc": elo_per_mc,
        "weightedRmse": (squared_error / total_weight) ** 0.5,
        "values": [
            {"name": name, "kind": "production" if name in production_names else "tag", "valueMc": fitted_values[name]}
            for name in feature_names
        ],
        "cards": results,
        "assumptions": assumptions,
    }


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
    smooth: bool = False,
) -> list[dict[str, Any]]:
    """Return locally calculated starting-item combinations and baseline lifts."""
    require_dataset(directory)
    if combination_type not in COMBINATION_TYPES:
        raise ValueError(f"Unknown combination type: {combination_type}")
    if stage not in {"starting_hand", "draft"}:
        raise ValueError("stage must be starting_hand or draft")
    if draft_number is not None and draft_number < 1:
        raise ValueError("draft_number must be at least 1")

    if smooth:
        center = combination_stats(
            directory, combination_type=combination_type, stage=stage, draft_number=draft_number,
            prelude=prelude, maps=maps, min_average_elo=min_average_elo,
            max_average_elo=max_average_elo, smooth=False,
        )
        adjacent: list[list[dict[str, Any]]] = []
        if stage == "starting_hand":
            adjacent.append(combination_stats(
                directory, combination_type=combination_type, stage="draft", draft_number=2,
                prelude=prelude, maps=maps, min_average_elo=min_average_elo,
                max_average_elo=max_average_elo, smooth=False,
            ))
        elif draft_number is not None:
            if draft_number > 2:
                adjacent.append(combination_stats(
                    directory, combination_type=combination_type, stage="draft", draft_number=draft_number - 1,
                    prelude=prelude, maps=maps, min_average_elo=min_average_elo,
                    max_average_elo=max_average_elo, smooth=False,
                ))
            adjacent.append(combination_stats(
                directory, combination_type=combination_type, stage="draft", draft_number=draft_number + 1,
                prelude=prelude, maps=maps, min_average_elo=min_average_elo,
                max_average_elo=max_average_elo, smooth=False,
            ))
        return _smooth_display_metrics(
            center, adjacent, key=("name1", "name2"), metrics=(
                "keepRate", "avgEloChange", "avgEloNotKept", "winRate", "baseline1Elo",
                "baseline2Elo", "notKept1Elo", "notKept2Elo", "lift1", "lift2", "totalLift",
            ),
        )
    first_kind, second_kind = COMBINATION_TYPES[combination_type]
    first_items = _combination_items(
        directory, first_kind, stage=stage, draft_number=draft_number
    )
    second_items = _combination_items(
        directory, second_kind, stage=stage, draft_number=draft_number
    )
    first_offered_items = _combination_offered_items(
        directory, first_kind, stage=stage, draft_number=draft_number
    )
    second_offered_items = _combination_offered_items(
        directory, second_kind, stage=stage, draft_number=draft_number
    )
    first_not_kept_items = _combination_not_kept_items(
        directory, first_kind, stage=stage, draft_number=draft_number
    )
    second_not_kept_items = _combination_not_kept_items(
        directory, second_kind, stage=stage, draft_number=draft_number
    )
    same_kind_filter = "AND i1.Name < i2.Name" if first_kind == second_kind else ""

    # A generation-specific card view compares every item inside the population
    # that actually reached and produced a selected card in that generation.
    uses_draft_cards = stage == "draft" and "card" in (first_kind, second_kind)
    if uses_draft_cards:
        card_items = _combination_offered_items(
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
             first_offered_items AS ({first_offered_items}),
             second_offered_items AS ({second_offered_items}),
             first_not_kept_items AS ({first_not_kept_items}),
             second_not_kept_items AS ({second_not_kept_items}),
             corporation_baselines AS (
                 SELECT i.Name, avg(ep.EloChange) AS avgEloChange
                 FROM first_items i
                 JOIN eligible_players ep USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             first_baselines AS (
                 SELECT i.Name,
                        count(*) AS gameCount,
                        avg(ap.EloChange) AS avgEloChange,
                        avg(CASE WHEN ap.Position = 1 THEN 1.0 ELSE 0.0 END) AS winRate
                 FROM first_items i
                 JOIN active_players ap USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             second_baselines AS (
                 SELECT i.Name,
                        count(*) AS gameCount,
                        avg(ap.EloChange) AS avgEloChange,
                        avg(CASE WHEN ap.Position = 1 THEN 1.0 ELSE 0.0 END) AS winRate
                 FROM second_items i
                 JOIN active_players ap USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             first_not_kept_baselines AS (
                 SELECT i.Name,
                        count(*) AS gameCount,
                        avg(ap.EloChange) AS avgEloChange
                 FROM first_not_kept_items i
                 JOIN active_players ap USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             second_not_kept_baselines AS (
                 SELECT i.Name,
                        count(*) AS gameCount,
                        avg(ap.EloChange) AS avgEloChange
                 FROM second_not_kept_items i
                 JOIN active_players ap USING (TableId, PlayerId)
                 GROUP BY i.Name
             ),
             combo_values AS (
                 SELECT i1.Name AS name1, i2.Name AS name2,
                        count(*) AS gameCount,
                        avg(ap.EloChange) AS avgEloChange,
                        avg(CASE WHEN ap.Position = 1 THEN 1.0 ELSE 0.0 END) AS winRate
                 FROM first_items i1
                 JOIN second_items i2 USING (TableId, PlayerId)
                 JOIN active_players ap ON ap.TableId = i1.TableId AND ap.PlayerId = i1.PlayerId
                 WHERE 1 = 1 {same_kind_filter}
                 GROUP BY i1.Name, i2.Name
             ),
             combo_offered_values AS (
                 SELECT i1.Name AS name1, i2.Name AS name2,
                        count(*) AS gameCount
                 FROM first_offered_items i1
                 JOIN second_offered_items i2 USING (TableId, PlayerId)
                 JOIN active_players ap ON ap.TableId = i1.TableId AND ap.PlayerId = i1.PlayerId
                 WHERE 1 = 1 {same_kind_filter}
                 GROUP BY i1.Name, i2.Name
             ),
             combo_not_kept_values AS (
                 SELECT i1.Name AS name1, i2.Name AS name2,
                        count(*) AS gameCount,
                        avg(ap.EloChange) AS avgEloChange
                 FROM first_items i1
                 JOIN second_not_kept_items i2 USING (TableId, PlayerId)
                 JOIN active_players ap ON ap.TableId = i1.TableId AND ap.PlayerId = i1.PlayerId
                 WHERE 1 = 1 {same_kind_filter}
                 GROUP BY i1.Name, i2.Name
             )
        SELECT o.name1, o.name2,
               CAST(COALESCE(c.gameCount, 0) AS BIGINT) AS gameCount,
               CAST(o.gameCount AS BIGINT) AS offeredGames,
               1.0 * COALESCE(c.gameCount, 0) / NULLIF(o.gameCount, 0) AS keepRate,
               c.avgEloChange, c.winRate,
               b1.avgEloChange AS baseline1Elo,
               cb.avgEloChange AS corporationBaselineElo,
               b2.avgEloChange AS baseline2Elo,
               b1n.avgEloChange AS notKept1Elo,
               b2n.avgEloChange AS notKept2Elo,
               CAST(n.gameCount AS BIGINT) AS notKeptGames,
               n.avgEloChange AS avgEloNotKept,
               CAST(b1.gameCount AS BIGINT) AS baseline1Games,
               CAST(b2.gameCount AS BIGINT) AS baseline2Games,
               CASE WHEN c.avgEloChange IS NOT NULL AND b1.avgEloChange IS NOT NULL
                    THEN c.avgEloChange - b1.avgEloChange END AS lift1,
               CASE WHEN c.avgEloChange IS NOT NULL AND b2.avgEloChange IS NOT NULL
                    THEN c.avgEloChange - b2.avgEloChange END AS lift2,
               CASE WHEN c.avgEloChange IS NOT NULL
                          AND b1.avgEloChange IS NOT NULL AND b2.avgEloChange IS NOT NULL
                    THEN c.avgEloChange - b1.avgEloChange - b2.avgEloChange END AS totalLift
        FROM combo_offered_values o
        LEFT JOIN combo_values c ON c.name1 = o.name1 AND c.name2 = o.name2
        LEFT JOIN first_baselines b1 ON b1.Name = o.name1
        LEFT JOIN corporation_baselines cb ON cb.Name = o.name1
        LEFT JOIN second_baselines b2 ON b2.Name = o.name2
        LEFT JOIN first_not_kept_baselines b1n ON b1n.Name = o.name1
        LEFT JOIN second_not_kept_baselines b2n ON b2n.Name = o.name2
        LEFT JOIN combo_not_kept_values n ON n.name1 = o.name1 AND n.name2 = o.name2
        ORDER BY totalLift DESC NULLS LAST, o.gameCount DESC, o.name1, o.name2
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
