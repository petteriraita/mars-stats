#!/usr/bin/env python3
"""Local web server and JSON API for the Mars statistics database."""

from __future__ import annotations

import json
import os
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from stats_engine import (
    DEFAULT_DATA_DIR,
    DEFAULT_DB,
    card_breakdown as sqlite_card_breakdown,
    combination_stats as sqlite_combination_stats,
    connect,
    rebuild,
    starting_hand_stats as sqlite_starting_hand_stats,
    status as sqlite_status,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SCRAPER_DATA_DIR", DEFAULT_DATA_DIR)).expanduser().resolve()
DATABASE = Path(os.environ.get("MARS_STATS_DB", DEFAULT_DB)).expanduser().resolve()
PARQUET_DIRECTORY = Path(
    os.environ.get("MARS_STATS_PARQUET_DIR", ROOT / "data" / "tfmstats_db")
).expanduser().resolve()
PARQUET_MODE = (PARQUET_DIRECTORY / "startinghandcards.parquet").is_file()
REBUILD_LOCK = threading.Lock()

if PARQUET_MODE:
    from parquet_stats import (
        card_breakdown as parquet_card_breakdown,
        combination_stats as parquet_combination_stats,
        starting_hand_stats as parquet_starting_hand_stats,
        status as parquet_status,
    )


def integer_parameter(query: dict[str, list[str]], name: str) -> int | None:
    value = query.get(name, [""])[0]
    if value == "":
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def query_filters(query: dict[str, list[str]]) -> tuple[str, int | None, int | None]:
    stage = query.get("stage", ["starting_hand"])[0]
    if stage not in {"starting_hand", "draft"}:
        raise ValueError("stage must be starting_hand or draft")
    return stage, integer_parameter(query, "draft_number"), integer_parameter(query, "pick_number")


def cohort_parameters(
    query: dict[str, list[str]], *, default_prelude: bool | None = None
) -> tuple[bool | None, tuple[str, ...] | None, int, int]:
    prelude_value = query.get("prelude", [""])[0].strip().lower()
    if not prelude_value:
        prelude = default_prelude
    elif prelude_value == "on":
        prelude = True
    elif prelude_value == "off":
        prelude = False
    elif prelude_value == "either":
        prelude = None
    else:
        raise ValueError("prelude must be on, off, or either")
    maps_value = query.get("maps", [""])[0].strip()
    maps = tuple(dict.fromkeys(name.strip() for name in maps_value.split(",") if name.strip())) or None
    min_average_elo = integer_parameter(query, "min_average_elo") or 0
    max_average_elo = integer_parameter(query, "max_average_elo") or 0
    if min_average_elo < 0:
        raise ValueError("min_average_elo must be zero or greater")
    if max_average_elo < 0:
        raise ValueError("max_average_elo must be zero or greater")
    if min_average_elo and max_average_elo and min_average_elo > max_average_elo:
        raise ValueError("min_average_elo cannot exceed max_average_elo")
    return prelude, maps, min_average_elo, max_average_elo


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, status_code: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def api_get(self, route: str, query: dict[str, list[str]]) -> None:
        if PARQUET_MODE:
            if route == "/api/status":
                self.send_json(HTTPStatus.OK, parquet_status(PARQUET_DIRECTORY))
                return
            if route == "/api/starting-hands":
                stage, draft_number, pick_number = query_filters(query)
                prelude, maps, min_average_elo, max_average_elo = cohort_parameters(query)
                self.send_json(HTTPStatus.OK, {
                    "data": parquet_starting_hand_stats(
                        PARQUET_DIRECTORY, stage, draft_number, pick_number,
                        prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo,
                    ),
                    "source": parquet_status(
                        PARQUET_DIRECTORY, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo,
                    ),
                    "filters": {"stage": stage, "draftNumber": draft_number, "pickNumber": pick_number},
                })
                return
            if route == "/api/combinations":
                stage, draft_number, pick_number = query_filters(query)
                if pick_number is not None:
                    raise ValueError("Combinations do not support draft pick position")
                combination_type = query.get("combo_type", ["card-card"])[0].strip()
                prelude, maps, min_average_elo, max_average_elo = cohort_parameters(query, default_prelude=True)
                self.send_json(HTTPStatus.OK, {
                    "combinations": parquet_combination_stats(
                        PARQUET_DIRECTORY,
                        combination_type=combination_type, stage=stage, draft_number=draft_number,
                        prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo,
                    ),
                    "source": parquet_status(
                        PARQUET_DIRECTORY, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo,
                    ),
                    "filters": {
                        "stage": stage, "draftNumber": draft_number,
                        "combinationType": combination_type,
                    },
                })
                return
            if route == "/api/card-breakdown":
                name = query.get("card", [""])[0].strip()
                if not name:
                    raise ValueError("card is required")
                prelude, maps, min_average_elo, max_average_elo = cohort_parameters(query)
                self.send_json(HTTPStatus.OK, {
                    "card": name,
                    "data": parquet_card_breakdown(
                        PARQUET_DIRECTORY, name, prelude=prelude, maps=maps, min_average_elo=min_average_elo, max_average_elo=max_average_elo,
                    ),
                })
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"detail": "Unknown local API route"})
            return

        connection = connect(DATABASE)
        try:
            if route == "/api/status":
                self.send_json(HTTPStatus.OK, sqlite_status(connection, DATABASE))
                return
            if route == "/api/starting-hands":
                stage, draft_number, pick_number = query_filters(query)
                self.send_json(HTTPStatus.OK, {
                    "data": sqlite_starting_hand_stats(connection, stage, draft_number, pick_number),
                    "source": sqlite_status(connection, DATABASE),
                    "filters": {"stage": stage, "draftNumber": draft_number, "pickNumber": pick_number},
                })
                return
            if route == "/api/combinations":
                stage, draft_number, pick_number = query_filters(query)
                self.send_json(HTTPStatus.OK, {
                    "combinations": sqlite_combination_stats(connection, stage, draft_number, pick_number),
                    "source": sqlite_status(connection, DATABASE),
                    "filters": {"stage": stage, "draftNumber": draft_number, "pickNumber": pick_number},
                })
                return
            if route == "/api/card-breakdown":
                name = query.get("card", [""])[0].strip()
                if not name:
                    raise ValueError("card is required")
                self.send_json(HTTPStatus.OK, {"card": name, "data": sqlite_card_breakdown(connection, name)})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"detail": "Unknown local API route"})
        finally:
            connection.close()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                self.api_get(parsed.path, parse_qs(parsed.query, keep_blank_values=True))
            except (BrokenPipeError, ConnectionResetError):
                return
            except ValueError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"detail": str(error)})
            except Exception as error:  # Keep API failures visible to the local UI.
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": str(error)})
            return
        super().do_GET()

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route != "/api/rebuild":
            self.send_json(HTTPStatus.NOT_FOUND, {"detail": "Unknown local API route"})
            return
        if not REBUILD_LOCK.acquire(blocking=False):
            self.send_json(HTTPStatus.CONFLICT, {"detail": "A local rebuild is already running"})
            return
        try:
            if PARQUET_MODE:
                self.send_json(HTTPStatus.OK, {
                    "ingestion": {"mode": "parquet", "files": len(list(PARQUET_DIRECTORY.glob("*.parquet")))},
                    "source": parquet_status(PARQUET_DIRECTORY),
                })
            else:
                counts = rebuild(DATA_DIR, DATABASE)
                connection = connect(DATABASE)
                try:
                    self.send_json(HTTPStatus.OK, {"ingestion": counts, "source": sqlite_status(connection, DATABASE)})
                finally:
                    connection.close()
        except Exception as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": str(error)})
        finally:
            REBUILD_LOCK.release()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[mars-stats] {fmt % args}")


def initialize_database() -> None:
    if PARQUET_MODE:
        parquet_status(PARQUET_DIRECTORY)
        return
    database_exists = DATABASE.exists()
    connection = connect(DATABASE)
    connection.close()
    if not database_exists and DATA_DIR.exists():
        rebuild(DATA_DIR, DATABASE)


if __name__ == "__main__":
    initialize_database()
    port = int(os.environ.get("PORT", "8080"))
    os.chdir(ROOT)
    print(f"Terraforming Mars Statistics running at http://localhost:{port}")
    if PARQUET_MODE:
        print(f"Local Parquet dataset: {PARQUET_DIRECTORY}")
    else:
        print(f"Local database: {DATABASE}")
        print(f"Replay source: {DATA_DIR}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
