#!/usr/bin/env python3
"""Download and extract the public TFMStats Parquet database bundle."""

from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from parquet_stats import DEFAULT_PARQUET_DIR, REQUIRED_TABLES


ROOT = Path(__file__).resolve().parent
PUBLIC_BUNDLE_URL = "https://api.tfmstats.com/api/download-db"
DEFAULT_ARCHIVE = ROOT / "data" / "tfmstats_db.zip"


def download(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = Request(
        PUBLIC_BUNDLE_URL,
        headers={"Accept": "application/zip", "User-Agent": "mars-stats-local/2.0"},
    )
    downloaded = 0
    with urlopen(request, timeout=600) as response, partial.open("wb") as output:
        total = int(response.headers.get("Content-Length", "0"))
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            downloaded += len(chunk)
            if total:
                print(
                    f"\rDownloaded {downloaded / 1024**2:,.1f} / {total / 1024**2:,.1f} MiB "
                    f"({downloaded / total:.1%})",
                    end="",
                    flush=True,
                )
            else:
                print(f"\rDownloaded {downloaded / 1024**2:,.1f} MiB", end="", flush=True)
    print()
    if not zipfile.is_zipfile(partial):
        partial.unlink(missing_ok=True)
        raise RuntimeError("The server response is not a valid ZIP archive")
    partial.replace(destination)


def extract(archive_path: Path, destination: Path) -> None:
    if not zipfile.is_zipfile(archive_path):
        raise RuntimeError(f"Invalid ZIP archive: {archive_path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        for member in members:
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
                raise RuntimeError(f"Unsafe or unexpected archive member: {member.filename}")
        names = {member.filename for member in members}
        missing = [f"{table}.parquet" for table in REQUIRED_TABLES if f"{table}.parquet" not in names]
        if missing:
            raise RuntimeError(f"Dataset bundle is incomplete: missing {', '.join(missing)}")
        with tempfile.TemporaryDirectory(prefix="tfmstats-extract-", dir=destination.parent) as temporary:
            temporary_path = Path(temporary)
            archive.extractall(temporary_path)
            destination.mkdir(parents=True, exist_ok=True)
            for parquet in temporary_path.glob("*.parquet"):
                parquet.replace(destination / parquet.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PARQUET_DIR)
    parser.add_argument("--force", action="store_true", help="download again even when the ZIP already exists")
    parser.add_argument("--download-only", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.force or not arguments.archive.is_file():
            download(arguments.archive)
        else:
            print(f"Using existing archive: {arguments.archive}")
        print(f"Archive size: {arguments.archive.stat().st_size / 1024**2:,.1f} MiB")
        if not arguments.download_only:
            extract(arguments.archive, arguments.output_dir)
            print(f"Extracted local database: {arguments.output_dir}")
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Dataset download failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
