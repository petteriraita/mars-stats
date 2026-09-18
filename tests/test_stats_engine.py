from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stats_engine import card_breakdown, combination_stats, connect, rebuild, starting_hand_stats, status


def game(game_id: str, player_id: str, elo: float, won: bool, *, colonies: bool = False) -> dict:
    return {
        "replay_id": game_id,
        "player_perspective": player_id,
        "prelude_on": True,
        "colonies_on": colonies,
        "draft_on": True,
        "ranked": True,
        "map": "Tharsis",
        "winner_id": player_id if won else "opponent",
        "players": {
            player_id: {
                "player_name": f"Player {player_id}",
                "elo_data": {"elo_change": elo},
                "starting_hand": {
                    "offered_cards": ["Cartel", "Earth Office", "Sponsors"],
                    "kept_cards": ["Cartel", "Earth Office"] if won else ["Sponsors"],
                },
                "draft_picks": [
                    {"generation": 2, "pick_number": 1, "offered_cards": ["AI Central", "Research"], "selected_card": "AI Central" if won else "Research"},
                    {"generation": 2, "pick_number": 2, "offered_cards": ["Media Group", "Acquired Company"], "selected_card": "Media Group" if won else "Acquired Company"},
                    {"generation": 3, "pick_number": 1, "offered_cards": ["Cartel", "Research"], "selected_card": "Research"},
                ],
            },
            "opponent": {"player_name": "Opponent", "elo_data": {"elo_change": -elo}},
        },
    }


def hstrand_game() -> dict:
    p1_cards = ["Cartel", "Earth Office", "Sponsors", "Research", "AI Central", "Media Group", "Towing a Comet", "Pets", "Dust Seals", "Power Grid"]
    p2_cards = ["Olympus Conference", "Mars University", "Acquired Company", "Imported GHG", "Invention Contest", "CEO's Favorite Project", "Mining Rights", "Space Mirrors", "Adaptation Technology", "Robotic Workforce"]
    state = lambda generation: {"generation": generation}
    return {
        "replay_id": "native-1", "player_perspective": "p1", "prelude_on": True,
        "colonies_on": False, "draft_on": True, "map": "Tharsis", "winner": "One",
        "players": {
            "p1": {"player_id": "p1", "player_name": "One", "starting_hand": {"corporations": [], "preludes": [], "project_cards": ["Cartel", "Earth Office"]}, "elo_data": {"game_rank_change": 4}},
            "p2": {"player_id": "p2", "player_name": "Two", "starting_hand": {"corporations": [], "preludes": [], "project_cards": ["Mars University"]}, "elo_data": {"game_rank_change": -4}},
        },
        "moves": [
            {"move_number": 1, "action_type": "other", "card_options": {"p1": p1_cards, "p2": p2_cards}, "game_state": state(1)},
            {"move_number": 2, "action_type": "pass", "card_options": {"p1": ["A", "B", "C", "D"], "p2": ["E", "F", "G", "H"]}, "game_state": state(2)},
            {"move_number": 3, "action_type": "draft", "player_id": "p1", "card_drafted": "A", "game_state": state(2)},
            {"move_number": 4, "action_type": "draft", "player_id": "p2", "card_drafted": "E", "card_options": {"p1": ["F", "G", "H"], "p2": ["B", "C", "D"]}, "game_state": state(2)},
            {"move_number": 5, "action_type": "draft", "player_id": "p1", "card_drafted": "F", "game_state": state(2)},
            {"move_number": 6, "action_type": "draft", "player_id": "p2", "card_drafted": "B", "card_options": {"p1": ["C", "D"], "p2": ["G", "H"]}, "game_state": state(2)},
            {"move_number": 7, "action_type": "draft", "player_id": "p1", "card_drafted": "C", "game_state": state(2)},
            {"move_number": 8, "action_type": "draft", "player_id": "p2", "card_drafted": "G", "card_options": {"p1": ["H"], "p2": ["D"]}, "game_state": state(2)},
            {"move_number": 9, "action_type": "buy_card", "player_id": "p1", "card_drafted": "A", "cards_kept": {"p1": ["A"], "p2": ["E"]}, "game_state": state(2)},
        ],
    }


class StatsEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.data = root / "parsed"
        self.data.mkdir()
        self.database = root / "stats.sqlite3"
        first = game("1001", "p1", 4.0, True)
        second = game("1002", "p2", -2.0, False)
        excluded = game("1003", "p3", 50.0, True, colonies=True)
        (self.data / "game_1001.json").write_text(json.dumps(first))
        # A duplicate perspective must replace, not double-count, the same player-game.
        (self.data / "duplicate_1001.json").write_text(json.dumps(first))
        (self.data / "game_1002.json").write_text(json.dumps(second))
        (self.data / "game_1003.json").write_text(json.dumps(excluded))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rebuild_filters_cohort_and_deduplicates(self) -> None:
        result = rebuild(self.data, self.database)
        self.assertEqual(result["games"], 2)
        self.assertEqual(result["skipped_cohort"], 1)
        connection = connect(self.database)
        local_status = status(connection, self.database)
        connection.close()
        self.assertEqual(local_status["games"], 2)
        self.assertEqual(local_status["offers"], 18)

    def test_starting_hand_kept_and_passed_elo(self) -> None:
        rebuild(self.data, self.database)
        connection = connect(self.database)
        rows = {row["cardName"]: row for row in starting_hand_stats(connection)}
        connection.close()
        cartel = rows["Cartel"]
        self.assertEqual(cartel["offeredGames"], 2)
        self.assertEqual(cartel["keptGames"], 1)
        self.assertEqual(cartel["notKeptGames"], 1)
        self.assertEqual(cartel["keepRate"], 50.0)
        self.assertEqual(cartel["avgEloGainOffered"], 1.0)
        self.assertEqual(cartel["avgEloGainKept"], 4.0)
        self.assertEqual(cartel["avgEloGainNotKept"], -2.0)

    def test_draft_and_pick_filters_are_independent(self) -> None:
        rebuild(self.data, self.database)
        connection = connect(self.database)
        draft_two = {row["cardName"]: row for row in starting_hand_stats(connection, "draft", 2, None)}
        pick_two = {row["cardName"]: row for row in starting_hand_stats(connection, "draft", 2, 2)}
        breakdown = card_breakdown(connection, "Cartel")
        connection.close()
        self.assertEqual(draft_two["AI Central"]["avgEloGainKept"], 4.0)
        self.assertEqual(draft_two["AI Central"]["avgEloGainNotKept"], -2.0)
        self.assertNotIn("AI Central", pick_two)
        self.assertIn("Media Group", pick_two)
        self.assertEqual([(row["stage"], row["draftNumber"]) for row in breakdown], [("starting_hand", 0), ("draft", 3)])

    def test_combinations_use_kept_cards_only(self) -> None:
        rebuild(self.data, self.database)
        connection = connect(self.database)
        combinations = combination_stats(connection)
        connection.close()
        pairs = {(row["cardA"], row["cardB"]): row for row in combinations}
        pair = pairs[("Cartel", "Earth Office")]
        self.assertEqual(pair["games"], 1)
        self.assertEqual(pair["winRate"], 100.0)
        self.assertEqual(pair["avgEloGain"], 4.0)

    def test_rebuild_reads_json_directly_from_zip_export(self) -> None:
        archive = Path(self.temporary.name) / "community-export.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("parsed/p1/game_2001.json", json.dumps(game("2001", "p1", 3.0, True)))
        database = Path(self.temporary.name) / "archive.sqlite3"
        result = rebuild(archive, database)
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["games"], 1)
        self.assertEqual(result["offers"], 9)

    def test_native_hstrand_moves_reconstruct_draft_offers(self) -> None:
        source = Path(self.temporary.name) / "native"
        source.mkdir()
        (source / "game_native.json").write_text(json.dumps(hstrand_game()))
        database = Path(self.temporary.name) / "native.sqlite3"
        result = rebuild(source, database)
        self.assertEqual(result["games"], 2)
        self.assertEqual(result["offers"], 28)
        connection = connect(database)
        draft = {row["cardName"]: row for row in starting_hand_stats(connection, "draft", 2)}
        p1_rows = connection.execute(
            """SELECT card_name, kept FROM card_offers
               WHERE game_id = 'native-1' AND player_id = 'p1'
                 AND stage = 'draft' AND draft_number = 2
               ORDER BY card_name"""
        ).fetchall()
        p2_rows = connection.execute(
            """SELECT card_name, kept FROM card_offers
               WHERE game_id = 'native-1' AND player_id = 'p2'
                 AND stage = 'draft' AND draft_number = 2
               ORDER BY card_name"""
        ).fetchall()
        connection.close()
        self.assertEqual([tuple(row) for row in p1_rows], [("A", 1), ("C", 0), ("F", 0), ("H", 0)])
        self.assertEqual([tuple(row) for row in p2_rows], [("B", 0), ("D", 0), ("E", 1), ("G", 0)])
        self.assertEqual(draft["A"]["keptGames"], 1)
        self.assertEqual(draft["A"]["avgEloGainKept"], 4)
        self.assertEqual(draft["F"]["notKeptGames"], 1)
        self.assertEqual(draft["F"]["avgEloGainNotKept"], 4)
        self.assertEqual(draft["E"]["avgEloGainKept"], -4)

    def test_native_hstrand_moves_preserve_three_known_cards_when_fourth_is_missing(self) -> None:
        replay = hstrand_game()
        replay["moves"][7].pop("card_options")
        source = Path(self.temporary.name) / "three-card-native"
        source.mkdir()
        (source / "game_native.json").write_text(json.dumps(replay))
        database = Path(self.temporary.name) / "three-card-native.sqlite3"

        result = rebuild(source, database)
        connection = connect(database)
        counts = connection.execute(
            """SELECT player_id, count(*)
               FROM card_offers
               WHERE stage = 'draft' AND draft_number = 2
               GROUP BY player_id ORDER BY player_id"""
        ).fetchall()
        connection.close()

        self.assertEqual(result["offers"], 26)
        self.assertEqual([tuple(row) for row in counts], [("p1", 3), ("p2", 3)])


if __name__ == "__main__":
    unittest.main()
