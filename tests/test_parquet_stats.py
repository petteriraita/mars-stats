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

    def test_research_generation_two_uses_known_final_hand_cards_and_bought_cards(self) -> None:
        rows = {row["cardName"]: row for row in parquet_stats.starting_hand_stats(DATASET, "draft", 2)}
        cartel = rows["Cartel"]
        self.assertEqual(cartel["offeredGames"], 6_372)
        self.assertEqual(cartel["keptGames"], 4_984)
        self.assertEqual(cartel["notKeptGames"], 1_388)
        draft_sql = parquet_stats._draft_offers(DATASET)
        self.assertIn("gc.DraftedGen AS DraftNumber", draft_sql)
        self.assertIn("gc.KeptGen = gc.DraftedGen", draft_sql)
        self.assertIn("gc.DraftedGen >= 2", draft_sql)
        self.assertNotIn("HAVING count(*) = 4", draft_sql)
        self.assertNotIn("gc.DrawnGen AS DraftNumber", draft_sql)
        self.assertEqual(
            parquet_stats.starting_hand_stats(DATASET, "draft", 1),
            [],
        )

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

    def test_card_combinations_keep_small_samples_and_return_raw_metrics(self) -> None:
        rows = parquet_stats.combination_stats(DATASET)
        self.assertEqual(len(rows), 23_005)
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
        self.assertIsNotNone(sparse["avgEloChange"])
        self.assertIsNotNone(sparse["winRate"])
        self.assertIsNotNone(sparse["totalLift"])
        nineteen = next(
            row for row in rows
            if (row["name1"], row["name2"]) == ("AI Central", "Ice cap Melting")
        )
        self.assertEqual(nineteen["gameCount"], 19)
        self.assertIsNotNone(nineteen["avgEloChange"])
        twenty = next(
            row for row in rows
            if (row["name1"], row["name2"]) == ("Deimos Down", "Worms")
        )
        self.assertEqual(twenty["gameCount"], 20)
        self.assertIsNotNone(twenty["avgEloChange"])
        hundred = next(row for row in rows if row["gameCount"] >= 100 and row["avgEloChange"] is not None)
        self.assertIsNotNone(hundred["winRate"])
        never_kept = next(
            row for row in rows
            if (row["name1"], row["name2"]) == ("Caretaker Contract", "Ore Processor")
        )
        self.assertEqual(never_kept["gameCount"], 0)
        self.assertEqual(never_kept["offeredGames"], 670)

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

    def test_corp_card_not_kept_metric_is_conditioned_on_the_corporation(self) -> None:
        rows = parquet_stats.combination_stats(
            DATASET,
            combination_type="corp-card",
            prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450,
        )
        row = next(
            item
            for item in rows
            if (item["name1"], item["name2"])
            == ("PhoboLog", "Aerobraked Ammonia Asteroid")
        )
        self.assertEqual(row["notKeptGames"], 222)
        self.assertIsNotNone(row["avgEloNotKept"])
        self.assertNotEqual(row["avgEloNotKept"], row["notKept2Elo"])
        self.assertEqual(row["offeredGames"], row["gameCount"] + row["notKeptGames"])
        self.assertAlmostEqual(row["keepRate"], row["gameCount"] / row["offeredGames"])
        self.assertIsNotNone(row["corporationBaselineElo"])

    def test_corp_prelude_not_kept_metric_is_available(self) -> None:
        rows = parquet_stats.combination_stats(
            DATASET,
            combination_type="corp-prelude",
            prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450,
        )
        row = next(
            item
            for item in rows
            if (item["name1"], item["name2"]) == ("CrediCor", "Society Support")
        )
        self.assertEqual((row["gameCount"], row["offeredGames"], row["notKeptGames"]), (73, 1_707, 1_634))
        self.assertIsNotNone(row["avgEloNotKept"])

    def test_standalone_corporation_rankings_are_available(self) -> None:
        rows = parquet_stats.item_stats(
            DATASET,
            kind="corp",
            prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450,
        )
        self.assertTrue(rows)
        ecoline = next(row for row in rows if row["name"] == "Ecoline")
        self.assertGreaterEqual(ecoline["gameCount"], 100)
        self.assertIsNotNone(ecoline["avgEloChange"])
        self.assertEqual(ecoline["offeredGames"], ecoline["gameCount"] + ecoline["notKeptGames"])
        self.assertIsNotNone(ecoline["avgEloNotKept"])
        with self.assertRaisesRegex(ValueError, "corporations or preludes"):
            parquet_stats.item_stats(DATASET, kind="card")

    def test_played_card_statistics_compare_played_and_held_cards(self) -> None:
        rows = parquet_stats.played_card_stats(
            DATASET,
            generation=2,
            prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450,
        )
        row = next(
            item for item in rows
            if (item["corporation"], item["card"]) == ("Tharsis Republic", "CEO's Favourite Project")
        )
        # The decision set includes cards bought in this generation and cards
        # bought earlier that were still unplayed at its start.
        self.assertEqual((row["acquiredGames"], row["playedGames"], row["notPlayedGames"]), (208, 2, 206))
        self.assertEqual(row["playedGames"] + row["notPlayedGames"], row["acquiredGames"])
        self.assertIsNotNone(row["corporationBaselineElo"])
        with self.assertRaisesRegex(ValueError, "between 1 and 14"):
            parquet_stats.played_card_stats(DATASET, generation=15)

    def test_card_detail_has_draft_and_play_rows_for_every_generation(self) -> None:
        draft_rows = parquet_stats.card_breakdown(
            DATASET, "Sabotage", prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450,
        )
        draft_gen3 = next(row for row in draft_rows if row["stage"] == "draft" and row["draftNumber"] == 3)
        self.assertEqual((draft_gen3["offered"], draft_gen3["kept"], draft_gen3["notKept"]), (3448, 3312, 136))
        self.assertIsNotNone(draft_gen3["winRateKept"])

        played_rows = parquet_stats.played_card_breakdown(
            DATASET, "Sabotage", prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450,
        )
        self.assertEqual([row["generation"] for row in played_rows], list(range(1, 15)))
        gen3 = next(row for row in played_rows if row["generation"] == 3)
        self.assertEqual(gen3["available"], gen3["played"] + gen3["notPlayed"])

        conditioned = parquet_stats.played_card_breakdown(
            DATASET, "Sabotage", prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450, corporation="CrediCor",
        )
        self.assertTrue(conditioned)
        self.assertIsNotNone(conditioned[0]["corporationBaselineElo"])

    def test_gen1_mc_production_model_is_corporation_stratified_and_reproducible(self) -> None:
        analysis = parquet_stats.gen1_mc_production_analysis(
            DATASET,
            prelude=True,
            maps=("Tharsis", "Hellas", "Elysium", "Vastitas Borealis"),
            min_average_elo=450,
        )
        self.assertEqual(analysis["resource"], "Production and tags")
        self.assertEqual(analysis["generation"], 1)
        self.assertAlmostEqual(analysis["mcProductionValue"], 6.111040296, places=6)
        self.assertAlmostEqual(analysis["eloPerMc"], 0.136697751, places=6)
        cards = {row["name"]: row for row in analysis["cards"]}
        self.assertEqual(len(cards), 26)
        values = {row["name"]: row["valueMc"] for row in analysis["values"]}
        self.assertAlmostEqual(values["jovian"], 2.076209704, places=6)
        self.assertAlmostEqual(values["earth"], 0.0, places=6)
        self.assertEqual(cards["Sponsors"]["playedGames"], 8_715)
        self.assertAlmostEqual(cards["Sponsors"]["observedEloDelta"], 0.375558460, places=6)

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
