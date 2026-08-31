# Starting Hand cohort comparison

Generated 2026-08-31 from the local TFMStats Parquet snapshot updated 2026-08-30T09:34:36+00:00.

## What is being compared

- **TFMStats reference:** two players, Draft on, Colonies off, non-friendly, Prelude either, every recorded map, no Elo cutoff. This reproduces the downloaded site's 215 Starting Hand rows.
- **Competitive pooled:** the same base rules, but Prelude on, Tharsis/Hellas/Elysium/Vastitas Borealis only, and average table Elo at least 450.
- **Current UI Average Elo Gain:** the raw group average, matching the reference page's metric. Cohort-adjusted delta fields remain in the analysis CSV for research.

The sequential cohorts below isolate Prelude, Amazonis/Random, and Elo-threshold effects. A three-map cohort is retained as a research comparison, but Vastitas is part of the app default. These are descriptive associations, not causal card-strength estimates.

## Cohort sizes

| Cohort | Games | Player-games | Offers | Cohort avg Elo gain |
|---|---:|---:|---:|---:|
| TFMStats reference | 186,815 | 373,637 | 3,727,660 | +0.15 |
| Prelude on, every recorded map | 174,007 | 348,021 | 3,473,350 | +0.11 |
| Prelude on, excluding Amazonis and Random | 173,130 | 346,267 | 3,455,810 | +0.11 |
| Prelude on, three-map comparison | 158,140 | 316,285 | 3,155,990 | +0.12 |
| Competitive pooled | 95,816 | 191,638 | 1,912,730 | +0.01 |
| Competitive Tharsis | 49,273 | 98,548 | 981,850 | +0.02 |
| Competitive Hellas | 26,524 | 53,048 | 530,460 | +0.01 |
| Competitive Elysium | 10,307 | 20,616 | 206,160 | +0.01 |
| Competitive Vastitas Borealis | 9,712 | 19,426 | 194,260 | +0.01 |

The competitive dataset retains 51.3% of reference player-games. Its analytical cohort baseline is only +0.014 Elo per row; the UI reports raw gain without subtracting it.

## Previous site numbers versus the current UI

Cards below have at least 500 offers in both cohorts. Both “Before” and “After” are raw Average Elo Gain; only the cohort filters change.

### Largest offered-Elo number changes

| Direction | Card | Before | After | Change (Elo) | Offers before → after |
|---|---|---:|---:|---:|---:|
| Down | Great Dam | -0.17 | -0.53 | -0.36 | 17,478 → 8,900 |
| Down | Interstellar Colony Ship | -0.07 | -0.42 | -0.35 | 17,136 → 8,720 |
| Down | Soletta | -0.20 | -0.54 | -0.34 | 17,508 → 8,962 |
| Down | Callisto Penal Mines | -0.06 | -0.39 | -0.33 | 17,413 → 8,875 |
| Down | Noctis Farming | +0.04 | -0.28 | -0.32 | 17,366 → 8,867 |
| Up | Restricted Area | +1.56 | +2.08 | +0.52 | 17,583 → 9,017 |
| Up | AI Central | +1.84 | +2.28 | +0.44 | 17,190 → 8,823 |
| Up | Earth Catapult | +2.31 | +2.74 | +0.43 | 17,417 → 8,739 |
| Up | Research Outpost | +1.59 | +1.91 | +0.32 | 17,356 → 8,983 |
| Up | Development Center | +1.00 | +1.24 | +0.24 | 17,362 → 8,851 |

### Largest keep-rate changes

| Direction | Card | Reference | Competitive | Change (percentage points) | Offers before → after |
|---|---|---:|---:|---:|---:|
| Down | Release of Inert Gases | 26.9% | 18.5% | -8.4 pp | 17,423 → 8,919 |
| Down | Solar Power | 40.3% | 32.9% | -7.4 pp | 17,421 → 8,942 |
| Down | Urbanized Area | 29.0% | 22.1% | -6.9 pp | 17,164 → 8,795 |
| Down | Phobos Space Haven | 51.9% | 45.8% | -6.1 pp | 17,450 → 8,886 |
| Down | Underground City | 45.9% | 39.9% | -6.0 pp | 17,548 → 8,959 |
| Up | Virus | 73.1% | 84.1% | +11.0 pp | 17,375 → 8,795 |
| Up | Heat Trappers | 63.1% | 73.6% | +10.5 pp | 16,907 → 8,662 |
| Up | Indentured Workers | 74.0% | 83.8% | +9.9 pp | 17,198 → 8,860 |
| Up | Sabotage | 84.5% | 93.4% | +9.0 pp | 17,228 → 8,807 |
| Up | Hired Raiders | 86.2% | 94.8% | +8.6 pp | 17,524 → 8,921 |

## Which filter caused the differences?

| Filter step | Games removed | Median absolute offered-Elo change | Largest absolute change |
|---|---:|---:|---:|
| Prelude-on filter | 12,808 | 0.037 | 0.096 |
| Remove Amazonis and Random | 877 | 0.002 | 0.014 |
| Require 450 average table Elo | 77,314 | 0.145 | 0.481 |

### Prelude-on filter

| Direction | Card | Before | After | Change (Elo) | Offers before → after |
|---|---|---:|---:|---:|---:|
| Down | Flooding | +0.19 | +0.09 | -0.10 | 17,551 → 16,313 |
| Down | Mineral Deposit | +0.15 | +0.06 | -0.09 | 17,371 → 16,130 |
| Down | Mohole Area | +0.65 | +0.56 | -0.09 | 17,601 → 16,380 |
| Up | Restricted Area | +1.56 | +1.59 | +0.03 | 17,583 → 16,330 |
| Up | Domed Crater | +0.01 | +0.03 | +0.02 | 17,225 → 16,004 |
| Up | Olympus Conference | +0.87 | +0.89 | +0.02 | 17,183 → 16,001 |

### Remove Amazonis and Random

| Direction | Card | Before | After | Change (Elo) | Offers before → after |
|---|---|---:|---:|---:|---:|
| Down | Eos Chasma National Park | -0.03 | -0.03 | -0.01 | 16,314 → 16,229 |
| Down | Investment Loan | -0.03 | -0.04 | -0.01 | 16,161 → 16,080 |
| Down | Hackers | +0.47 | +0.47 | -0.01 | 16,217 → 16,125 |
| Up | Earth Catapult | +2.27 | +2.28 | +0.01 | 16,176 → 16,084 |
| Up | Media Group | +1.00 | +1.01 | +0.01 | 16,124 → 16,043 |
| Up | Land Claim | -0.06 | -0.06 | +0.01 | 16,033 → 15,957 |

### Require 450 average table Elo

| Direction | Card | Before | After | Change (Elo) | Offers before → after |
|---|---|---:|---:|---:|---:|
| Down | Great Dam | -0.20 | -0.53 | -0.33 | 16,171 → 8,900 |
| Down | Callisto Penal Mines | -0.08 | -0.39 | -0.31 | 16,091 → 8,875 |
| Down | Interstellar Colony Ship | -0.12 | -0.42 | -0.30 | 15,815 → 8,720 |
| Up | Restricted Area | +1.60 | +2.08 | +0.48 | 16,246 → 9,017 |
| Up | Earth Catapult | +2.28 | +2.74 | +0.46 | 16,084 → 8,739 |
| Up | AI Central | +1.84 | +2.28 | +0.44 | 15,939 → 8,823 |

## Map-specific differences

Each map uses the same Prelude-on and 450+ average-table-Elo rules. The change is that map's offered Elo delta minus the other three maps combined, so the samples do not overlap. Approximate z-scores use the card-level standard errors; repeated players and 215 simultaneous card checks mean they are diagnostics, not formal proof.

### Tharsis versus the other maps

| Direction | Card | Other maps | This map | Change (Elo) | Approx. z | Offers other → map |
|---|---|---:|---:|---:|---:|---:|
| Down | Asteroid Mining Consortium | +1.28 | +0.69 | -0.60 | -3.2 | 4,408 → 4,487 |
| Down | Nuclear Zone | +1.50 | +0.97 | -0.53 | -2.9 | 4,433 → 4,609 |
| Down | Asteroid Mining | +0.36 | -0.17 | -0.53 | -2.9 | 4,331 → 4,580 |
| Down | Callisto Penal Mines | -0.15 | -0.64 | -0.49 | -2.7 | 4,307 → 4,568 |
| Down | Psychrophiles | +0.98 | +0.56 | -0.42 | -2.3 | 4,237 → 4,557 |
| Up | Giant Ice Asteroid | +0.44 | +1.20 | +0.76 | +4.2 | 4,349 → 4,550 |
| Up | Mohole Area | +0.19 | +0.89 | +0.69 | +3.8 | 4,310 → 4,661 |
| Up | Wave Power | -0.63 | -0.04 | +0.59 | +3.2 | 4,212 → 4,621 |
| Up | Ice Asteroid | -0.04 | +0.50 | +0.55 | +3.0 | 4,352 → 4,597 |
| Up | Subterranean Reservoir | -0.20 | +0.23 | +0.43 | +2.4 | 4,387 → 4,662 |

### Hellas versus the other maps

| Direction | Card | Other maps | This map | Change (Elo) | Approx. z | Offers other → map |
|---|---|---:|---:|---:|---:|---:|
| Down | Mohole Area | +0.76 | +0.02 | -0.74 | -3.7 | 6,429 → 2,542 |
| Down | Protected Valley | +0.21 | -0.35 | -0.56 | -2.8 | 6,480 → 2,428 |
| Down | Comet | +0.24 | -0.28 | -0.52 | -2.6 | 6,344 → 2,506 |
| Down | Invention Contest | +0.35 | -0.15 | -0.50 | -2.5 | 6,460 → 2,555 |
| Down | Energy Saving | -0.19 | -0.66 | -0.47 | -2.3 | 6,592 → 2,486 |
| Up | Asteroid Mining Consortium | +0.77 | +1.53 | +0.76 | +3.7 | 6,407 → 2,488 |
| Up | Plantation | -0.61 | +0.11 | +0.72 | +3.5 | 6,369 → 2,462 |
| Up | Olympus Conference | +0.69 | +1.25 | +0.56 | +2.7 | 6,347 → 2,415 |
| Up | Underground Detonations | -0.50 | -0.08 | +0.42 | +2.1 | 6,442 → 2,567 |
| Up | Research Coordination | -0.07 | +0.35 | +0.42 | +2.0 | 6,390 → 2,454 |

### Elysium versus the other maps

| Direction | Card | Other maps | This map | Change (Elo) | Approx. z | Offers other → map |
|---|---|---:|---:|---:|---:|---:|
| Down | AI Central | +2.35 | +1.52 | -0.84 | -2.9 | 7,882 → 941 |
| Down | Development Center | +1.31 | +0.56 | -0.76 | -2.5 | 7,897 → 954 |
| Down | Wave Power | -0.25 | -0.92 | -0.67 | -2.3 | 7,897 → 936 |
| Down | Mining Rights | +1.23 | +0.59 | -0.64 | -2.3 | 8,083 → 1,024 |
| Down | Physics Complex | -0.33 | -0.94 | -0.62 | -2.2 | 8,048 → 947 |
| Up | Nuclear Zone | +1.14 | +1.99 | +0.86 | +3.0 | 8,070 → 972 |
| Up | Birds | -0.08 | +0.65 | +0.73 | +2.6 | 7,903 → 969 |
| Up | Ice cap Melting | -0.43 | +0.25 | +0.68 | +2.4 | 7,753 → 951 |
| Up | Ants | -0.46 | +0.16 | +0.61 | +2.2 | 7,897 → 944 |
| Up | Satellites | -0.25 | +0.36 | +0.61 | +2.2 | 7,836 → 968 |

### Vastitas Borealis versus the other maps

| Direction | Card | Other maps | This map | Change (Elo) | Approx. z | Offers other → map |
|---|---|---:|---:|---:|---:|---:|
| Down | Local Heat Trapping | -0.19 | -1.08 | -0.89 | -3.1 | 7,898 → 918 |
| Down | Giant Ice Asteroid | +0.91 | +0.15 | -0.76 | -2.7 | 7,968 → 931 |
| Down | Mine | +0.68 | -0.04 | -0.72 | -2.4 | 8,118 → 894 |
| Down | Industrial Microbes | +0.46 | -0.19 | -0.65 | -2.2 | 8,049 → 900 |
| Down | Cupola City | -0.04 | -0.68 | -0.64 | -2.2 | 7,869 → 935 |
| Up | Flooding | -0.21 | +0.78 | +0.99 | +3.4 | 8,034 → 897 |
| Up | Worms | -0.50 | +0.49 | +0.99 | +3.3 | 8,015 → 930 |
| Up | Media Group | +1.09 | +1.99 | +0.90 | +3.1 | 7,944 → 886 |
| Up | Mining Rights | +1.09 | +1.77 | +0.68 | +2.4 | 8,169 → 938 |
| Up | Nuclear Zone | +1.16 | +1.83 | +0.67 | +2.3 | 8,114 → 928 |

## Reading the results

- Offered Average Elo Gain is the most stable UI comparison because every offer contributes.
- Kept/not-kept splits can be much noisier for cards that are nearly always or almost never kept; inspect their group counts in `starting_hand_by_cohort.csv` before acting on them.
- Each normal game contributes one observation for each player. Four reference tables contain extra canonical player rows, so exact game counts use distinct table IDs rather than dividing player-games by two.
- Refreshing the source Parquet bundle can change every result; rerun this script after a refresh.

## Reproduce

```bash
cd /home/pt/dev/mars-stats
.venv/bin/python analysis/cohort_analysis.py
```

Machine-readable outputs: `cohort_summary.csv`, `starting_hand_by_cohort.csv`, and `map_contrasts.csv` in this directory.
