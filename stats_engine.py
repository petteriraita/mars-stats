#!/usr/bin/env python3
"""Local ingestion and statistics engine for Terraforming Mars replay exports."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = Path(os.environ.get("SCRAPER_DATA_DIR", ROOT / "data" / "parsed")).expanduser().resolve()
DEFAULT_DB = Path(os.environ.get("MARS_STATS_DB", ROOT / "data" / "mars_stats.sqlite3")).expanduser().resolve()


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    game_date TEXT,
    map_name TEXT,
    elo_change REAL NOT NULL,
    won INTEGER NOT NULL CHECK (won IN (0, 1)),
    source_file TEXT NOT NULL,
    PRIMARY KEY (game_id, player_id)
);
CREATE TABLE IF NOT EXISTS card_offers (
    game_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('starting_hand', 'draft')),
    draft_number INTEGER NOT NULL DEFAULT 0,
    pick_number INTEGER NOT NULL DEFAULT 0,
    card_name TEXT NOT NULL,
    kept INTEGER NOT NULL CHECK (kept IN (0, 1)),
    PRIMARY KEY (game_id, player_id, stage, draft_number, pick_number, card_name),
    FOREIGN KEY (game_id, player_id) REFERENCES games(game_id, player_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS offers_filter_idx
    ON card_offers(stage, draft_number, pick_number, card_name);
CREATE INDEX IF NOT EXISTS offers_game_idx
    ON card_offers(game_id, player_id, kept);
"""


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def first(mapping: Mapping[str, Any] | None, keys: Sequence[str], default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return default


def nested(mapping: Mapping[str, Any] | None, *paths: Sequence[str]) -> Any:
    for path in paths:
        value: Any = mapping
        for key in path:
            if not isinstance(value, Mapping) or key not in value:
                value = None
                break
            value = value[key]
        if value is not None and value != "":
            return value
    return None


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled", "ranked", "arena"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", "unranked", "friendly"}:
            return False
    return None


def as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def card_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        direct = first(value, ["name", "card_name", "cardName", "card"])
        if direct is not None:
            return card_names(direct)
        names: list[str] = []
        for key, enabled in value.items():
            if as_bool(enabled) is True:
                names.extend(card_names(key))
        return names
    if isinstance(value, Sequence):
        names = []
        for item in value:
            names.extend(card_names(item))
        return list(dict.fromkeys(names))
    return []


def iter_games(payload: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping):
                yield item
        return
    if not isinstance(payload, Mapping):
        return
    games = payload.get("games")
    if isinstance(games, list):
        yield from (item for item in games if isinstance(item, Mapping))
    elif "replay_id" in payload or "game_id" in payload or "table_id" in payload:
        yield payload


def json_documents(source: Path) -> Iterator[tuple[str, Any, bool]]:
    """Yield (source name, decoded payload/error, success) without extracting archives."""
    paths = [source] if source.is_file() else sorted(source.rglob("*.json")) + sorted(source.rglob("*.zip")) if source.is_dir() else []
    for path in paths:
        if path.name == "complete_summary.json":
            continue
        if path.suffix.lower() == ".json":
            try:
                yield str(path), json.loads(path.read_text(encoding="utf-8")), True
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                yield str(path), error, False
            continue
        if path.suffix.lower() != ".zip":
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                members = sorted(name for name in archive.namelist() if name.lower().endswith(".json") and not name.endswith("complete_summary.json"))
                for name in members:
                    try:
                        with archive.open(name) as stream:
                            yield f"{path}!{name}", json.load(stream), True
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                        yield f"{path}!{name}", error, False
        except (OSError, zipfile.BadZipFile) as error:
            yield str(path), error, False


def player_count(game: Mapping[str, Any]) -> int:
    players = game.get("players")
    if isinstance(players, (Mapping, Sequence)) and not isinstance(players, str):
        return len(players)
    return as_int(first(game, ["player_count", "playerCount", "num_players", "numPlayers"]), -1)


def player_record(game: Mapping[str, Any], player_id: str) -> Mapping[str, Any]:
    players = game.get("players")
    if isinstance(players, Mapping):
        record = players.get(player_id)
        if record is None:
            record = players.get(as_int(player_id, -1))
        return record if isinstance(record, Mapping) else {}
    if isinstance(players, list):
        for record in players:
            if isinstance(record, Mapping) and str(first(record, ["player_id", "playerId", "id"], "")) == player_id:
                return record
    return {}


def perspective_id(game: Mapping[str, Any]) -> str | None:
    value = first(game, ["player_perspective", "playerPerspective", "perspective_player_id", "perspectivePlayerId"])
    if value is not None:
        return str(value)
    players = game.get("players")
    if isinstance(players, Mapping) and len(players) == 1:
        return str(next(iter(players)))
    return None


def elo_change(game: Mapping[str, Any], player: Mapping[str, Any]) -> float | None:
    value = nested(
        player,
        ("elo_data", "elo_change"),
        ("elo_data", "eloChange"),
        ("elo_data", "game_rank_change"),
        ("elo_data", "gameRankChange"),
        ("elo_data", "arena_points_change"),
        ("elo_data", "arenaPointsChange"),
    )
    if value is None:
        value = first(player, ["elo_change", "eloChange", "elo_gain", "eloGain", "rating_change", "ratingChange"])
    if value is None:
        value = first(game, ["elo_change", "eloChange", "elo_gain", "eloGain"])
    return as_float(value)


def player_won(game: Mapping[str, Any], player_id: str, player: Mapping[str, Any]) -> bool:
    explicit = as_bool(first(player, ["won", "is_winner", "isWinner"]));
    if explicit is not None:
        return explicit
    winner = first(game, ["winner_id", "winnerId", "winner"])
    if winner is None:
        return False
    player_name = str(first(player, ["player_name", "playerName", "name"], ""))
    return str(winner) in {player_id, player_name}


def ranked_game(game: Mapping[str, Any], player: Mapping[str, Any]) -> bool:
    explicit = as_bool(first(game, ["ranked", "is_ranked", "isRanked", "arena", "is_arena", "isArena"]));
    if explicit is not None:
        return explicit
    mode = str(first(game, ["game_mode", "gameMode", "mode", "competition"], "")).lower()
    if mode:
        return "arena" in mode or "ranked" in mode
    # HStrand indexes Arena games; an Elo block is therefore a safe schema-level signal.
    return isinstance(player.get("elo_data"), Mapping)


def cohort_matches(game: Mapping[str, Any], player: Mapping[str, Any]) -> bool:
    if player_count(game) != 2 or not ranked_game(game, player):
        return False
    colonies = as_bool(first(game, ["colonies_on", "coloniesOn", "colonies", "use_colonies", "useColonies"]));
    draft = as_bool(first(game, ["draft_on", "draftOn", "draft", "draft_variant", "draftVariant"]));
    # This deliberately matches the public Starting Hand query. Prelude is not
    # part of that cohort; both Prelude-on and Prelude-off games are included.
    return colonies is False and draft is True


def offer_from_record(record: Mapping[str, Any], stage: str, fallback_draft: int = 0) -> list[dict[str, Any]]:
    containers = [record]
    for key in ("details", "data", "args", "payload"):
        child = record.get(key)
        if isinstance(child, Mapping):
            containers.append(child)
    offered: list[str] = []
    kept: list[str] = []
    for container in containers:
        if not offered:
            offered = card_names(first(container, [
                "offered_cards", "offeredCards", "cards_offered", "cardsOffered",
                "available_cards", "availableCards", "initial_cards", "initialCards",
                "offer", "offered",
            ]))
        if not kept:
            kept = card_names(first(container, [
                "kept_cards", "keptCards", "cards_kept", "cardsKept", "selected_cards",
                "selectedCards", "selected_card", "selectedCard", "chosen_cards", "chosenCards",
                "chosen_card", "chosenCard", "picked_cards", "pickedCards", "picked_card", "pickedCard",
            ]))
    if not offered:
        return []
    draft_number = as_int(first(record, ["draft_number", "draftNumber", "generation", "round", "round_number", "roundNumber"]), fallback_draft)
    pick_number = as_int(first(record, ["pick_number", "pickNumber", "pick", "position", "pass_number", "passNumber"]), 0)
    kept_set = set(kept)
    return [{
        "stage": stage,
        "draft_number": 0 if stage == "starting_hand" else draft_number,
        "pick_number": 0 if stage == "starting_hand" else pick_number,
        "card_name": name,
        "kept": int(name in kept_set),
    } for name in offered]


def move_generation(move: Mapping[str, Any]) -> int:
    state = first(move, ["game_state", "gameState"], {})
    return as_int(first(state, ["generation", "generation_number", "generationNumber"]), 0)


def hstrand_offers(game: Mapping[str, Any], player_id: str, player: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct offers from the native HStrand parser's Move fields."""
    observations: list[dict[str, Any]] = []
    starting_hand = first(player, ["starting_hand", "startingHand"], {})
    kept_starting = set(card_names(first(starting_hand, ["project_cards", "projectCards"])))
    moves = game.get("moves")
    if not isinstance(moves, list):
        return observations

    # setuppick options contain the ten project cards; the Player object contains those bought.
    if kept_starting:
        for move in moves:
            if not isinstance(move, Mapping):
                continue
            options = first(move, ["card_options", "cardOptions"])
            if not isinstance(options, Mapping):
                continue
            offered = card_names(options.get(player_id, options.get(as_int(player_id, -1))))
            if len(offered) < 5:
                continue
            observations.extend({
                "stage": "starting_hand", "draft_number": 0, "pick_number": 0,
                "card_name": card, "kept": int(card in kept_starting),
            } for card in offered)
            break

    # HStrand marks the start of every draft with a pass move containing the 4-card packs.
    index = 0
    while index < len(moves):
        move = moves[index]
        if not isinstance(move, Mapping):
            index += 1
            continue
        action = str(first(move, ["action_type", "actionType"], "")).lower()
        options = first(move, ["card_options", "cardOptions"])
        packs = [card_names(cards) for cards in options.values()] if isinstance(options, Mapping) else []
        if action != "pass" or not packs or not all(len(pack) == 4 for pack in packs):
            index += 1
            continue
        generation = move_generation(move)
        pack_states = [{"remaining": list(pack), "picks": 0} for pack in packs]
        index += 1
        while index < len(moves):
            draft_move = moves[index]
            if not isinstance(draft_move, Mapping):
                index += 1
                continue
            draft_action = str(first(draft_move, ["action_type", "actionType"], "")).lower()
            if draft_action == "buy_card":
                break
            if draft_action == "pass" and first(draft_move, ["card_options", "cardOptions"]):
                break
            if draft_action == "draft":
                selected_names = card_names(first(draft_move, ["card_drafted", "cardDrafted", "selected_card", "selectedCard"]))
                selecting_player = str(first(draft_move, ["player_id", "playerId"], ""))
                if selected_names and selecting_player == player_id:
                    selected = selected_names[0]
                    pack = next((candidate for candidate in pack_states if selected in candidate["remaining"]), None)
                    if pack is not None:
                        pick_number = as_int(pack["picks"]) + 1
                        observations.extend({
                            "stage": "draft", "draft_number": generation, "pick_number": pick_number,
                            "card_name": card, "kept": int(card == selected),
                        } for card in pack["remaining"])
                        pack["remaining"].remove(selected)
                        pack["picks"] = pick_number
                elif selected_names:
                    selected = selected_names[0]
                    pack = next((candidate for candidate in pack_states if selected in candidate["remaining"]), None)
                    if pack is not None:
                        pack["remaining"].remove(selected)
                        pack["picks"] = as_int(pack["picks"]) + 1
            index += 1
        # The fourth card is assigned automatically and has no reliable player move, so it is not inferred.
        index += 1
    return observations


def records_from(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
    elif isinstance(value, list):
        yield from (item for item in value if isinstance(item, Mapping))


def extract_offers(game: Mapping[str, Any], player: Mapping[str, Any], known_player_id: str | None = None) -> list[dict[str, Any]]:
    player_id = known_player_id or str(first(player, ["player_id", "playerId", "id"], ""))
    offers: list[dict[str, Any]] = hstrand_offers(game, player_id, player) if player_id else []
    for owner in (game, player):
        for key in ("starting_hand", "startingHand", "starting_hand_offer", "startingHandOffer"):
            for record in records_from(owner.get(key)):
                offers.extend(offer_from_record(record, "starting_hand"))
        for key in ("draft_picks", "draftPicks", "drafts", "card_offers", "cardOffers", "research_phases", "researchPhases"):
            for record in records_from(owner.get(key)):
                stage = str(first(record, ["stage", "type"], "draft")).lower()
                normalized_stage = "starting_hand" if "start" in stage or "initial" in stage else "draft"
                offers.extend(offer_from_record(record, normalized_stage))
    moves = game.get("moves")
    if isinstance(moves, list):
        for move in moves:
            if not isinstance(move, Mapping):
                continue
            action = str(first(move, ["action_type", "actionType", "type", "name"], "")).lower()
            if "draft" in action or "research" in action or "starting_hand" in action:
                stage = "starting_hand" if "start" in action or "initial" in action else "draft"
                offers.extend(offer_from_record(move, stage))
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for offer in offers:
        key = (offer["stage"], offer["draft_number"], offer["pick_number"], offer["card_name"])
        if key not in unique or offer["kept"]:
            unique[key] = offer
    return list(unique.values())


def rebuild(data_dir: Path = DEFAULT_DATA_DIR, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    connection = connect(db_path)
    counts = {"files": 0, "invalid_files": 0, "records": 0, "games": 0, "offers": 0, "skipped_cohort": 0, "skipped_schema": 0}
    with connection:
        connection.execute("DELETE FROM card_offers")
        connection.execute("DELETE FROM games")
        for source_name, payload, valid in json_documents(data_dir):
            counts["files"] += 1
            if not valid:
                counts["invalid_files"] += 1
                continue
            for game in iter_games(payload):
                counts["records"] += 1
                game_id = str(first(game, ["replay_id", "replayId", "game_id", "gameId", "table_id", "tableId"], ""))
                perspective = perspective_id(game)
                players = game.get("players")
                player_ids = list(players.keys()) if isinstance(players, Mapping) else []
                candidates = list(dict.fromkeys([str(value) for value in [perspective, *player_ids] if value is not None]))
                if not game_id or not candidates:
                    counts["skipped_schema"] += 1
                    continue
                accepted = False
                cohort_rejected = False
                for player_id in candidates:
                    player = player_record(game, player_id)
                    delta = elo_change(game, player)
                    observations = extract_offers(game, player, player_id)
                    if delta is None or not observations:
                        continue
                    if not cohort_matches(game, player):
                        cohort_rejected = True
                        continue
                    accepted = True
                    connection.execute(
                        """INSERT OR REPLACE INTO games
                           (game_id, player_id, game_date, map_name, elo_change, won, source_file)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (game_id, player_id, first(game, ["game_date", "gameDate", "date"]),
                         first(game, ["map", "map_name", "mapName"]), delta,
                         int(player_won(game, player_id, player)), source_name),
                    )
                    connection.execute("DELETE FROM card_offers WHERE game_id = ? AND player_id = ?", (game_id, player_id))
                    connection.executemany(
                        """INSERT INTO card_offers
                           (game_id, player_id, stage, draft_number, pick_number, card_name, kept)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        [(game_id, player_id, item["stage"], item["draft_number"], item["pick_number"], item["card_name"], item["kept"])
                         for item in observations],
                    )
                if not accepted:
                    counts["skipped_cohort" if cohort_rejected else "skipped_schema"] += 1
        counts["games"] = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        counts["offers"] = connection.execute("SELECT COUNT(*) FROM card_offers").fetchone()[0]
        updated = datetime.now(UTC).isoformat()
        metadata = {
            "updated_at": updated,
            "source_dir": str(data_dir.resolve()),
            "files_scanned": str(counts["files"]),
            "records_seen": str(counts["records"]),
            "skipped_cohort": str(counts["skipped_cohort"]),
            "skipped_schema": str(counts["skipped_schema"]),
        }
        connection.executemany("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", metadata.items())
    connection.close()
    return counts


def filters(stage: str, draft_number: int | None, pick_number: int | None, alias: str = "o") -> tuple[str, list[Any]]:
    clauses = [f"{alias}.stage = ?"]
    parameters: list[Any] = [stage]
    if draft_number is not None:
        clauses.append(f"{alias}.draft_number = ?")
        parameters.append(draft_number)
    if pick_number is not None:
        clauses.append(f"{alias}.pick_number = ?")
        parameters.append(pick_number)
    return " AND ".join(clauses), parameters


def starting_hand_stats(connection: sqlite3.Connection, stage: str = "starting_hand", draft_number: int | None = None, pick_number: int | None = None) -> list[dict[str, Any]]:
    where, parameters = filters(stage, draft_number, pick_number)
    rows = connection.execute(f"""
        SELECT o.card_name,
               COUNT(*) AS offered,
               SUM(o.kept) AS kept,
               SUM(1 - o.kept) AS not_kept,
               AVG(g.elo_change) AS elo_offered,
               AVG(CASE WHEN o.kept = 1 THEN g.elo_change END) AS elo_kept,
               AVG(CASE WHEN o.kept = 0 THEN g.elo_change END) AS elo_not_kept
        FROM card_offers o
        JOIN games g USING (game_id, player_id)
        WHERE {where}
        GROUP BY o.card_name
        ORDER BY elo_kept DESC, offered DESC, o.card_name
    """, parameters).fetchall()
    return [{
        "cardName": row["card_name"], "offeredGames": row["offered"], "keptGames": row["kept"],
        "notKeptGames": row["not_kept"], "keepRate": row["kept"] / row["offered"] * 100,
        "avgEloGainOffered": row["elo_offered"], "avgEloGainKept": row["elo_kept"],
        "avgEloGainNotKept": row["elo_not_kept"],
    } for row in rows]


def card_breakdown(connection: sqlite3.Connection, card_name: str) -> list[dict[str, Any]]:
    rows = connection.execute("""
        SELECT o.stage, o.draft_number, o.pick_number, COUNT(*) offered, SUM(o.kept) kept,
               AVG(g.elo_change) elo_offered,
               AVG(CASE WHEN o.kept = 1 THEN g.elo_change END) elo_kept,
               AVG(CASE WHEN o.kept = 0 THEN g.elo_change END) elo_not_kept
        FROM card_offers o JOIN games g USING (game_id, player_id)
        WHERE o.card_name = ?
        GROUP BY o.stage, o.draft_number, o.pick_number
        ORDER BY CASE o.stage WHEN 'starting_hand' THEN 0 ELSE 1 END, o.draft_number, o.pick_number
    """, (card_name,)).fetchall()
    return [{
        "stage": row["stage"], "draftNumber": row["draft_number"], "pickNumber": row["pick_number"],
        "offered": row["offered"], "kept": row["kept"], "notKept": row["offered"] - row["kept"],
        "keepRate": row["kept"] / row["offered"] * 100, "eloOffered": row["elo_offered"],
        "eloKept": row["elo_kept"], "eloNotKept": row["elo_not_kept"],
    } for row in rows]


def combination_stats(connection: sqlite3.Connection, stage: str = "starting_hand", draft_number: int | None = None, pick_number: int | None = None) -> list[dict[str, Any]]:
    where_a, parameters = filters(stage, draft_number, pick_number, "a")
    where_b, parameters_b = filters(stage, draft_number, pick_number, "b")
    rows = connection.execute(f"""
        WITH individual AS (
            SELECT o.card_name, AVG(g.elo_change) baseline
            FROM card_offers o JOIN games g USING (game_id, player_id)
            WHERE o.kept = 1 AND {where_a.replace('a.', 'o.')}
            GROUP BY o.card_name
        )
        SELECT a.card_name card_a, b.card_name card_b, COUNT(*) games,
               AVG(g.won) * 100.0 win_rate, AVG(g.elo_change) elo,
               AVG(g.elo_change) - (ia.baseline + ib.baseline) / 2.0 baseline_delta
        FROM card_offers a
        JOIN card_offers b ON a.game_id = b.game_id AND a.player_id = b.player_id AND a.card_name < b.card_name
        JOIN games g ON a.game_id = g.game_id AND a.player_id = g.player_id
        JOIN individual ia ON ia.card_name = a.card_name
        JOIN individual ib ON ib.card_name = b.card_name
        WHERE a.kept = 1 AND b.kept = 1 AND {where_a} AND {where_b}
        GROUP BY a.card_name, b.card_name
        ORDER BY elo DESC, games DESC
    """, parameters + parameters + parameters_b).fetchall()
    return [{"cardA": row["card_a"], "cardB": row["card_b"], "games": row["games"],
             "winRate": row["win_rate"], "avgEloGain": row["elo"], "vsBaseline": row["baseline_delta"]}
            for row in rows]


def status(connection: sqlite3.Connection, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    metadata = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
    games = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    offers = connection.execute("SELECT COUNT(*) FROM card_offers").fetchone()[0]
    cards = connection.execute("SELECT COUNT(DISTINCT card_name) FROM card_offers").fetchone()[0]
    stages = [dict(row) for row in connection.execute("""
        SELECT stage, draft_number AS draftNumber, pick_number AS pickNumber, COUNT(*) AS offers
        FROM card_offers GROUP BY stage, draft_number, pick_number
        ORDER BY stage, draft_number, pick_number
    """)]
    return {"database": str(db_path.resolve()), "games": games, "offers": offers, "cards": cards,
            "updatedAt": metadata.get("updated_at"), "sourceDir": metadata.get("source_dir", str(DEFAULT_DATA_DIR)),
            "filesScanned": as_int(metadata.get("files_scanned")), "recordsSeen": as_int(metadata.get("records_seen")),
            "skippedCohort": as_int(metadata.get("skipped_cohort")), "skippedSchema": as_int(metadata.get("skipped_schema")),
            "stages": stages}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "rebuild", "status"), nargs="?", default="status")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    arguments = parser.parse_args()
    if arguments.command == "rebuild":
        print(json.dumps(rebuild(arguments.data_dir, arguments.database), indent=2))
        return
    connection = connect(arguments.database)
    print(json.dumps(status(connection, arguments.database), indent=2))
    connection.close()


if __name__ == "__main__":
    main()
