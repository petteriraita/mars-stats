#!/usr/bin/env python3
"""Regenerate filtered Starting Hand datasets and cohort-comparison report."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parquet_stats import (  # noqa: E402
    DEFAULT_PARQUET_DIR,
    starting_hand_stats,
    status,
)


STANDARD_MAPS = ("Tharsis", "Hellas", "Elysium")
FOUR_REAL_MAPS = (*STANDARD_MAPS, "Vastitas Borealis")


@dataclass(frozen=True)
class Cohort:
    key: str
    label: str
    prelude: bool | None
    maps: tuple[str, ...] | None
    min_average_elo: int


COHORTS = (
    Cohort("tfmstats_reference", "TFMStats reference", None, None, 0),
    Cohort("prelude_all_maps", "Prelude on, every recorded map", True, None, 0),
    Cohort("prelude_without_amazonis_random", "Prelude on, excluding Amazonis and Random", True, FOUR_REAL_MAPS, 0),
    Cohort("prelude_standard_maps", "Prelude on, three-map comparison", True, STANDARD_MAPS, 0),
    Cohort("competitive", "Competitive pooled", True, FOUR_REAL_MAPS, 450),
    Cohort("competitive_tharsis", "Competitive Tharsis", True, ("Tharsis",), 450),
    Cohort("competitive_not_tharsis", "Competitive maps except Tharsis", True, ("Hellas", "Elysium", "Vastitas Borealis"), 450),
    Cohort("competitive_hellas", "Competitive Hellas", True, ("Hellas",), 450),
    Cohort("competitive_not_hellas", "Competitive maps except Hellas", True, ("Tharsis", "Elysium", "Vastitas Borealis"), 450),
    Cohort("competitive_elysium", "Competitive Elysium", True, ("Elysium",), 450),
    Cohort("competitive_not_elysium", "Competitive maps except Elysium", True, ("Tharsis", "Hellas", "Vastitas Borealis"), 450),
    Cohort("competitive_vastitas", "Competitive Vastitas Borealis", True, ("Vastitas Borealis",), 450),
    Cohort("competitive_not_vastitas", "Competitive maps except Vastitas", True, STANDARD_MAPS, 450),
)


CARD_COLUMNS = (
    "cardName",
    "offeredGames",
    "keptGames",
    "notKeptGames",
    "keepRate",
    "avgEloGainOffered",
    "avgEloGainKept",
    "avgEloGainNotKept",
    "stddevEloGainOffered",
    "stddevEloGainKept",
    "stddevEloGainNotKept",
    "avgEloDeltaOffered",
    "avgEloDeltaKept",
    "avgEloDeltaNotKept",
)


def cohort_kwargs(cohort: Cohort) -> dict[str, Any]:
    return {
        "prelude": cohort.prelude,
        "maps": cohort.maps,
        "min_average_elo": cohort.min_average_elo,
    }


def fmt_number(value: float | int | None, digits: int = 2, signed: bool = False) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.{digits}f}"


def card_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["cardName"]: row for row in rows}


def paired_rows(
    datasets: dict[str, list[dict[str, Any]]],
    left: str,
    right: str,
    *,
    minimum_offers: int,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    a = card_index(datasets[left])
    b = card_index(datasets[right])
    return [
        (name, a[name], b[name])
        for name in sorted(a.keys() & b.keys())
        if a[name]["offeredGames"] >= minimum_offers and b[name]["offeredGames"] >= minimum_offers
    ]


def largest(
    pairs: list[tuple[str, dict[str, Any], dict[str, Any]]],
    value: Callable[[dict[str, Any], dict[str, Any]], float | None],
    *,
    count: int,
    minimum_group: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
) -> tuple[list[tuple[str, float, dict[str, Any], dict[str, Any]]], list[tuple[str, float, dict[str, Any], dict[str, Any]]]]:
    values = []
    for name, left, right in pairs:
        if minimum_group and not minimum_group(left, right):
            continue
        difference = value(left, right)
        if difference is not None:
            values.append((name, difference, left, right))
    values.sort(key=lambda item: item[1])
    return values[:count], list(reversed(values[-count:]))


def change_table(
    title: str,
    negative: list[tuple[str, float, dict[str, Any], dict[str, Any]]],
    positive: list[tuple[str, float, dict[str, Any], dict[str, Any]]],
    *,
    left_metric: str,
    right_metric: str,
    unit: str = "Elo",
) -> list[str]:
    lines = [f"### {title}", "", f"| Direction | Card | Before | After | Change ({unit}) | Offers before → after |", "|---|---|---:|---:|---:|---:|"]
    for direction, items in (("Down", negative), ("Up", positive)):
        for name, difference, left, right in items:
            lines.append(
                f"| {direction} | {name} | {fmt_number(left[left_metric], signed=True)} | "
                f"{fmt_number(right[right_metric], signed=True)} | {fmt_number(difference, signed=True)} | "
                f"{left['offeredGames']:,} → {right['offeredGames']:,} |"
            )
    lines.append("")
    return lines


def map_contrasts(
    datasets: dict[str, list[dict[str, Any]]],
    map_key: str,
    rest_key: str,
    *,
    minimum_offers: int,
) -> list[dict[str, Any]]:
    contrasts = []
    for name, rest, map_row in paired_rows(datasets, rest_key, map_key, minimum_offers=minimum_offers):
        map_mean = map_row["avgEloDeltaOffered"]
        rest_mean = rest["avgEloDeltaOffered"]
        map_sd = map_row["stddevEloGainOffered"]
        rest_sd = rest["stddevEloGainOffered"]
        standard_error = math.sqrt(
            map_sd * map_sd / map_row["offeredGames"]
            + rest_sd * rest_sd / rest["offeredGames"]
        )
        difference = map_mean - rest_mean
        contrasts.append(
            {
                "card": name,
                "map_mean": map_mean,
                "rest_mean": rest_mean,
                "difference": difference,
                "standard_error": standard_error,
                "z_score": difference / standard_error if standard_error else None,
                "map_offers": map_row["offeredGames"],
                "rest_offers": rest["offeredGames"],
            }
        )
    return contrasts


def write_map_contrasts_csv(path: Path, datasets: dict[str, list[dict[str, Any]]], minimum_offers: int) -> None:
    fields = ("map", "card", "map_elo_delta", "other_maps_elo_delta", "difference", "approx_standard_error", "approx_z_score", "map_offers", "other_maps_offers")
    map_sets = (
        ("Tharsis", "competitive_tharsis", "competitive_not_tharsis"),
        ("Hellas", "competitive_hellas", "competitive_not_hellas"),
        ("Elysium", "competitive_elysium", "competitive_not_elysium"),
        ("Vastitas Borealis", "competitive_vastitas", "competitive_not_vastitas"),
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        for map_name, map_key, rest_key in map_sets:
            for row in sorted(map_contrasts(datasets, map_key, rest_key, minimum_offers=minimum_offers), key=lambda item: item["card"]):
                writer.writerow(
                    {
                        "map": map_name,
                        "card": row["card"],
                        "map_elo_delta": row["map_mean"],
                        "other_maps_elo_delta": row["rest_mean"],
                        "difference": row["difference"],
                        "approx_standard_error": row["standard_error"],
                        "approx_z_score": row["z_score"],
                        "map_offers": row["map_offers"],
                        "other_maps_offers": row["rest_offers"],
                    }
                )


def write_summary_csv(path: Path, cohorts: tuple[Cohort, ...], summaries: dict[str, dict[str, Any]]) -> None:
    fields = (
        "cohort",
        "label",
        "prelude",
        "maps",
        "min_average_elo",
        "games",
        "player_games",
        "starting_hand_offers",
        "cards",
        "cohort_avg_elo_gain",
        "snapshot_updated_at",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        for cohort in cohorts:
            summary = summaries[cohort.key]
            writer.writerow(
                {
                    "cohort": cohort.key,
                    "label": cohort.label,
                    "prelude": "either" if cohort.prelude is None else "on" if cohort.prelude else "off",
                    "maps": "all recorded" if cohort.maps is None else "|".join(cohort.maps),
                    "min_average_elo": cohort.min_average_elo,
                    "games": summary["gameCount"],
                    "player_games": summary["games"],
                    "starting_hand_offers": summary["offers"],
                    "cards": summary["cards"],
                    "cohort_avg_elo_gain": summary["cohortAvgEloGain"],
                    "snapshot_updated_at": summary["updatedAt"],
                }
            )


def write_cards_csv(path: Path, cohorts: tuple[Cohort, ...], datasets: dict[str, list[dict[str, Any]]]) -> None:
    fields = ("cohort", "label", *CARD_COLUMNS)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        for cohort in cohorts:
            for row in sorted(datasets[cohort.key], key=lambda item: item["cardName"]):
                writer.writerow({"cohort": cohort.key, "label": cohort.label, **{name: row.get(name) for name in CARD_COLUMNS}})


def generate_report(
    output: Path,
    summaries: dict[str, dict[str, Any]],
    datasets: dict[str, list[dict[str, Any]]],
    *,
    minimum_offers: int,
    top: int,
) -> None:
    reference = summaries["tfmstats_reference"]
    competitive = summaries["competitive"]
    lines = [
        "# Starting Hand cohort comparison",
        "",
        f"Generated {datetime.now(UTC).date().isoformat()} from the local TFMStats Parquet snapshot updated {reference['updatedAt']}.",
        "",
        "## What is being compared",
        "",
        "- **TFMStats reference:** two players, Draft on, Colonies off, non-friendly, Prelude either, every recorded map, no Elo cutoff. This reproduces the downloaded site's 215 Starting Hand rows.",
        "- **Competitive pooled:** the same base rules, but Prelude on, Tharsis/Hellas/Elysium/Vastitas Borealis only, and average table Elo at least 450.",
        "- **Current UI Average Elo Gain:** the raw group average, matching the reference page's metric. Cohort-adjusted delta fields remain in the analysis CSV for research.",
        "",
        "The sequential cohorts below isolate Prelude, Amazonis/Random, and Elo-threshold effects. A three-map cohort is retained as a research comparison, but Vastitas is part of the app default. These are descriptive associations, not causal card-strength estimates.",
        "",
        "## Cohort sizes",
        "",
        "| Cohort | Games | Player-games | Offers | Cohort avg Elo gain |",
        "|---|---:|---:|---:|---:|",
    ]
    cohort_by_key = {cohort.key: cohort for cohort in COHORTS}
    for key in ("tfmstats_reference", "prelude_all_maps", "prelude_without_amazonis_random", "prelude_standard_maps", "competitive", "competitive_tharsis", "competitive_hellas", "competitive_elysium", "competitive_vastitas"):
        summary = summaries[key]
        lines.append(
            f"| {cohort_by_key[key].label} | {summary['gameCount']:,} | {summary['games']:,} | "
            f"{summary['offers']:,} | {fmt_number(summary['cohortAvgEloGain'], signed=True)} |"
        )
    lines += [
        "",
        f"The competitive dataset retains {competitive['games'] / reference['games']:.1%} of reference player-games. Its analytical cohort baseline is only {competitive['cohortAvgEloGain']:+.3f} Elo per row; the UI reports raw gain without subtracting it.",
        "",
        "## Previous site numbers versus the current UI",
        "",
        f"Cards below have at least {minimum_offers:,} offers in both cohorts. Both “Before” and “After” are raw Average Elo Gain; only the cohort filters change.",
        "",
    ]
    total_pairs = paired_rows(datasets, "tfmstats_reference", "competitive", minimum_offers=minimum_offers)
    down, up = largest(
        total_pairs,
        lambda left, right: right["avgEloGainOffered"] - left["avgEloGainOffered"],
        count=top,
    )
    lines += change_table(
        "Largest offered-Elo number changes",
        down,
        up,
        left_metric="avgEloGainOffered",
        right_metric="avgEloGainOffered",
    )

    keep_down, keep_up = largest(
        total_pairs,
        lambda left, right: right["keepRate"] - left["keepRate"],
        count=top,
    )
    lines += [
        "### Largest keep-rate changes",
        "",
        "| Direction | Card | Reference | Competitive | Change (percentage points) | Offers before → after |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for direction, items in (("Down", keep_down), ("Up", keep_up)):
        for name, difference, left, right in items:
            lines.append(
                f"| {direction} | {name} | {left['keepRate']:.1f}% | {right['keepRate']:.1f}% | "
                f"{difference:+.1f} pp | {left['offeredGames']:,} → {right['offeredGames']:,} |"
            )
    steps = (
        ("Prelude-on filter", "tfmstats_reference", "prelude_all_maps"),
        ("Remove Amazonis and Random", "prelude_all_maps", "prelude_without_amazonis_random"),
        ("Require 450 average table Elo", "prelude_without_amazonis_random", "competitive"),
    )
    lines += [
        "",
        "## Which filter caused the differences?",
        "",
        "| Filter step | Games removed | Median absolute offered-Elo change | Largest absolute change |",
        "|---|---:|---:|---:|",
    ]
    for title, left_key, right_key in steps:
        pairs = paired_rows(datasets, left_key, right_key, minimum_offers=minimum_offers)
        changes = [right["avgEloGainOffered"] - left["avgEloGainOffered"] for _, left, right in pairs]
        lines.append(
            f"| {title} | {summaries[left_key]['gameCount'] - summaries[right_key]['gameCount']:,} | "
            f"{statistics.median(abs(value) for value in changes):.3f} | {max(abs(value) for value in changes):.3f} |"
        )
    lines.append("")
    for title, left_key, right_key in steps:
        pairs = paired_rows(datasets, left_key, right_key, minimum_offers=minimum_offers)
        down, up = largest(
            pairs,
            lambda left, right: right["avgEloGainOffered"] - left["avgEloGainOffered"],
            count=min(3, top),
        )
        lines += change_table(
            title,
            down,
            up,
            left_metric="avgEloGainOffered",
            right_metric="avgEloGainOffered",
        )

    lines += [
        "## Map-specific differences",
        "",
        "Each map uses the same Prelude-on and 450+ average-table-Elo rules. The change is that map's offered Elo delta minus the other three maps combined, so the samples do not overlap. Approximate z-scores use the card-level standard errors; repeated players and 215 simultaneous card checks mean they are diagnostics, not formal proof.",
        "",
    ]
    map_sets = (
        ("Tharsis", "competitive_tharsis", "competitive_not_tharsis"),
        ("Hellas", "competitive_hellas", "competitive_not_hellas"),
        ("Elysium", "competitive_elysium", "competitive_not_elysium"),
        ("Vastitas Borealis", "competitive_vastitas", "competitive_not_vastitas"),
    )
    for map_label, map_key, rest_key in map_sets:
        contrasts = map_contrasts(datasets, map_key, rest_key, minimum_offers=minimum_offers)
        contrasts.sort(key=lambda item: item["difference"])
        selected = (("Down", contrasts[:top]), ("Up", list(reversed(contrasts[-top:]))))
        lines += [
            f"### {map_label} versus the other maps",
            "",
            "| Direction | Card | Other maps | This map | Change (Elo) | Approx. z | Offers other → map |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for direction, items in selected:
            for row in items:
                lines.append(
                    f"| {direction} | {row['card']} | {fmt_number(row['rest_mean'], signed=True)} | "
                    f"{fmt_number(row['map_mean'], signed=True)} | {fmt_number(row['difference'], signed=True)} | "
                    f"{fmt_number(row['z_score'], digits=1, signed=True)} | {row['rest_offers']:,} → {row['map_offers']:,} |"
                )
        lines.append("")

    lines += [
        "## Reading the results",
        "",
        "- Offered Average Elo Gain is the most stable UI comparison because every offer contributes.",
        "- Kept/not-kept splits can be much noisier for cards that are nearly always or almost never kept; inspect their group counts in `starting_hand_by_cohort.csv` before acting on them.",
        "- Each normal game contributes one observation for each player. Four reference tables contain extra canonical player rows, so exact game counts use distinct table IDs rather than dividing player-games by two.",
        "- Refreshing the source Parquet bundle can change every result; rerun this script after a refresh.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "cd /home/pt/dev/mars-stats",
        ".venv/bin/python analysis/cohort_analysis.py",
        "```",
        "",
        "Machine-readable outputs: `cohort_summary.csv`, `starting_hand_by_cohort.csv`, and `map_contrasts.csv` in this directory.",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_PARQUET_DIR)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "analysis" / "output")
    parser.add_argument("--minimum-offers", type=int, default=500)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, Any]] = {}
    datasets: dict[str, list[dict[str, Any]]] = {}
    for cohort in COHORTS:
        kwargs = cohort_kwargs(cohort)
        summaries[cohort.key] = status(args.dataset, **kwargs)
        datasets[cohort.key] = starting_hand_stats(args.dataset, **kwargs)
        print(f"{cohort.key}: {summaries[cohort.key]['games']:,} player-games, {len(datasets[cohort.key])} cards")

    write_summary_csv(args.output_dir / "cohort_summary.csv", COHORTS, summaries)
    write_cards_csv(args.output_dir / "starting_hand_by_cohort.csv", COHORTS, datasets)
    write_map_contrasts_csv(args.output_dir / "map_contrasts.csv", datasets, max(1, args.minimum_offers))
    generate_report(
        args.output_dir / "REPORT.md",
        summaries,
        datasets,
        minimum_offers=max(1, args.minimum_offers),
        top=max(1, args.top),
    )
    print(f"Wrote analysis to {args.output_dir}")


if __name__ == "__main__":
    main()
