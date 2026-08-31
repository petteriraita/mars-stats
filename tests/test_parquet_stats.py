from __future__ import annotations

import unittest
from pathlib import Path

try:
    import parquet_stats
except (ModuleNotFoundError, RuntimeError):
    parquet_stats = None


DATASET = Path(__file__).resolve().parents[1] / "data" / "tfmstats_db"


@unittest.skipUnless(parquet_stats is not None and parquet_stats.available(DATASET), "local Parquet bundle not installed")
class ParquetStatsTests(unittest.TestCase):
    def test_starting_hand_matches_downloaded_tfmstats_snapshot(self) -> None:
        rows = {row["cardName"]: row for row in parquet_stats.starting_hand_stats(DATASET)}
        self.assertEqual(len(rows), 215)
        expected = {
            "Cartel": (17_288, 12_636, 4_652, 0.5076353540027765, 0.6578822412155746, 0.09952708512467756),
            "Earth Catapult": (17_417, 17_237, 180, 2.308836194522593, 2.329407669548065, 0.3388888888888889),
            "AI Central": (17_190, 16_452, 738, 1.835892961023851, 1.9406759056649647, -0.5),
            "Sponsors": (17_258, 16_825, 433, 0.49310464712017615, 0.5134621099554235, -0.2979214780600462),
            "Dust Seals": (17_342, 2_713, 14_629, -0.16163072309998847, -0.8024327312937707, -0.042791715086472074),
        }
        for card_name, values in expected.items():
            row = rows[card_name]
            self.assertEqual((row["offeredGames"], row["keptGames"], row["notKeptGames"]), values[:3])
            self.assertAlmostEqual(row["avgEloGainOffered"], values[3])
            self.assertAlmostEqual(row["avgEloGainKept"], values[4])
            self.assertAlmostEqual(row["avgEloGainNotKept"], values[5])

    def test_draft_generation_two_is_calculated_locally(self) -> None:
        rows = {row["cardName"]: row for row in parquet_stats.starting_hand_stats(DATASET, "draft", 2)}
        cartel = rows["Cartel"]
        self.assertEqual(cartel["offeredGames"], 12_496)
        self.assertEqual(cartel["keptGames"], 6_372)
        self.assertEqual(cartel["notKeptGames"], 6_124)

    def test_draft_rows_exclude_parser_artifacts(self) -> None:
        valid_cards = {
            row["cardName"] for row in parquet_stats.starting_hand_stats(DATASET)
        }
        all_draft_cards = set()
        for generation in range(1, 15):
            draft_cards = {
                row["cardName"]
                for row in parquet_stats.starting_hand_stats(DATASET, "draft", generation)
            }
            self.assertLessEqual(draft_cards, valid_cards)
            all_draft_cards.update(draft_cards)
        self.assertNotIn("Undo (no undo beyond this point)", all_draft_cards)
        self.assertNotIn("(no undo beyond this point)", all_draft_cards)

    def test_card_combinations_keep_small_samples_but_suppress_metrics(self) -> None:
        rows = parquet_stats.combination_stats(DATASET)
        self.assertEqual(len(rows), 23_002)
        ai_earth = next(
            row for row in rows
            if (row["name1"], row["name2"]) == ("AI Central", "Earth Catapult")
        )
        self.assertEqual(ai_earth["gameCount"], 630)
        sparse = next(
            row for row in rows
            if (row["name1"], row["name2"])
            == ("Caretaker Contract", "Underground Detonations")
        )
        self.assertEqual(sparse["gameCount"], 9)
        self.assertIsNone(sparse["avgEloChange"])
        self.assertIsNone(sparse["winRate"])
        self.assertIsNone(sparse["totalLift"])
        nineteen = next(
            row for row in rows
            if (row["name1"], row["name2"]) == ("AI Central", "Ice cap Melting")
        )
        self.assertEqual(nineteen["gameCount"], 19)
        self.assertIsNone(nineteen["avgEloChange"])
        twenty = next(
            row for row in rows
            if (row["name1"], row["name2"]) == ("Deimos Down", "Worms")
        )
        self.assertEqual(twenty["gameCount"], 20)
        self.assertIsNotNone(twenty["avgEloChange"])

    def test_all_combination_types_and_draft_generation_are_available(self) -> None:
        for combination_type in parquet_stats.COMBINATION_TYPES:
            rows = parquet_stats.combination_stats(
                DATASET, combination_type=combination_type
            )
            self.assertTrue(rows, combination_type)
        draft_rows = parquet_stats.combination_stats(
            DATASET,
            combination_type="corp-card",
            stage="draft",
            draft_number=2,
        )
        self.assertTrue(draft_rows)
        with self.assertRaisesRegex(ValueError, "Unknown combination type"):
            parquet_stats.combination_stats(DATASET, combination_type="invalid")

    def test_competitive_defaults_use_average_table_elo_and_four_maps(self) -> None:
        maps = ("Tharsis", "Hellas", "Elysium", "Vastitas Borealis")
        local_status = parquet_stats.status(DATASET, prelude=True, maps=maps, min_average_elo=450)
        self.assertEqual(local_status["gameCount"], 95_816)
        self.assertEqual(local_status["games"], 191_638)
        self.assertEqual(local_status["offers"], 1_912_730)
        rows = {
            row["cardName"]: row
            for row in parquet_stats.starting_hand_stats(
                DATASET, prelude=True, maps=maps, min_average_elo=450
            )
        }
        cartel = rows["Cartel"]
        self.assertEqual((cartel["offeredGames"], cartel["keptGames"], cartel["notKeptGames"]), (8_795, 6_708, 2_087))
        weighted_offered_delta = sum(
            row["avgEloDeltaOffered"] * row["offeredGames"] for row in rows.values()
        ) / sum(row["offeredGames"] for row in rows.values())
        self.assertAlmostEqual(weighted_offered_delta, 0.0, delta=0.001)
        self.assertAlmostEqual(
            cartel["avgEloDeltaOffered"],
            cartel["avgEloGainOffered"] - local_status["cohortAvgEloGain"],
        )
        self.assertAlmostEqual(
            cartel["avgEloDeltaKept"],
            cartel["avgEloGainKept"] - local_status["cohortAvgEloGain"],
        )
        with self.assertRaisesRegex(ValueError, "Unknown map"):
            parquet_stats.starting_hand_stats(DATASET, maps=("Amazonis Planitia",))

    def test_low_elo_range_has_an_upper_bound_and_keeps_all_cards(self) -> None:
        maps = ("Tharsis", "Hellas", "Elysium", "Vastitas Borealis")
        local_status = parquet_stats.status(DATASET, prelude=True, maps=maps, max_average_elo=200)
        self.assertEqual(local_status["gameCount"], 818)
        self.assertEqual(local_status["games"], 1_636)
        self.assertEqual(local_status["offers"], 16_320)
        rows = parquet_stats.starting_hand_stats(
            DATASET, prelude=True, maps=maps, max_average_elo=200
        )
        self.assertEqual(len(rows), 215)
        with self.assertRaisesRegex(ValueError, "Minimum average Elo"):
            parquet_stats.starting_hand_stats(
                DATASET, min_average_elo=450, max_average_elo=200
            )


if __name__ == "__main__":
    unittest.main()
