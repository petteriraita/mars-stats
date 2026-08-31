#!/usr/bin/env python3
"""Download the locally displayed card artwork from the public card-images repository."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import parquet_stats


ROOT = Path(__file__).resolve().parent
DESTINATION = ROOT / "assets" / "cards"
TREE_URL = "https://api.github.com/repos/terraforming-mars/card-images/git/trees/master?recursive=1"
RAW_URL = "https://raw.githubusercontent.com/terraforming-mars/card-images/master/"


def comparable(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def destination_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower().replace("'", "")).strip("_")


def source_slug(path: str) -> str:
    stem = Path(path).stem
    return re.sub(r"^(?:corp\d+|p\d+|\d+)-", "", stem)


ALIASES = {
    comparable("Allied Banks"): comparable("Allied Bank"),
    comparable("Biolabs"): comparable("Biolab"),
    comparable("Eccentric Sponsor"): comparable("Excentric Sponsor"),
    comparable("CEO's Favourite Project"): comparable("CEOs Favorite Project"),
}


def active_names() -> dict[str, set[str]]:
    directory = parquet_stats.DEFAULT_PARQUET_DIR
    cards = {row["cardName"] for row in parquet_stats.starting_hand_stats(directory)}
    combo_rows = parquet_stats.combination_stats(
        directory, combination_type="corp-prelude", prelude=True
    )
    corporations = {row["name1"] for row in combo_rows}
    preludes = {row["name2"] for row in combo_rows}
    return {"corp": corporations, "prelude": preludes, "card": cards}


def main() -> None:
    with urllib.request.urlopen(TREE_URL) as response:
        tree = json.load(response)["tree"]
    images = [item["path"] for item in tree if item["path"].lower().endswith(".png")]
    by_name = {comparable(source_slug(path)): path for path in images}

    downloaded = 0
    missing: list[str] = []
    for kind, names in active_names().items():
        directory = DESTINATION / kind
        directory.mkdir(parents=True, exist_ok=True)
        for name in sorted(names):
            key = ALIASES.get(comparable(name), comparable(name))
            source = by_name.get(key)
            if source is None:
                missing.append(f"{kind}: {name}")
                continue
            destination = directory / f"{destination_slug(name)}.png"
            if not destination.exists():
                urllib.request.urlretrieve(RAW_URL + source, destination)
                downloaded += 1

    print(f"Downloaded {downloaded} card images to {DESTINATION}")
    if missing:
        raise RuntimeError("No image match for: " + ", ".join(missing))


if __name__ == "__main__":
    main()
