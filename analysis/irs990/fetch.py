"""Steps 1-3: get the three public files we need, and cache them.

The IRS publishes 990 filings as monthly ZIP archives of XML, roughly 250MB each.
Downloading all of them would be wasteful, so we narrow first:

  1. The Business Master File lists every nonprofit WITH ITS ADDRESS. The filings
     themselves carry no state field, so this is the only way to find the local
     foundations before downloading anything large.
  2. The annual index is a table of contents: for each filing it gives the EIN,
     the form type, and which ZIP archive holds it.
  3. Only then do we download the handful of archives that actually contain the
     filings we want.

The directory and the indexes change as the IRS processes returns, so they are
re-downloaded once they are older than REFRESH_AFTER. A published archive never
changes, so archives are downloaded once and kept. Filings processed in a later
calendar year land in that year's index, so the current and previous index years
are read and each foundation's newest filing wins.

Why two index years: a return is indexed in the year the IRS processes it. A
foundation whose newest return is for tax year 2024 was processed in 2025, so
reading only the 2026 index missed it (two of the organization's own funders
among them). Every foundation files yearly, so the current and previous
index years together hold every on-time filer's newest return.
"""
from __future__ import annotations

import csv
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "irs990"
BMF_URL = "https://www.irs.gov/pub/irs-soi/eo_{state}.csv"
INDEX_URL = "https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv"
ARCHIVE_URL = "https://apps.irs.gov/pub/epostcard/990/xml/{year}/{batch}.zip"
USER_AGENT = "GrantIQ/1.0 (nonprofit public grant research; respectful, bounded retrieval)"

# ZIP prefixes or full ZIP codes. Duval is 322xx; Baker, Nassau, St. Johns and
# most of Clay share 320xx; Keystone Heights (32656) is the part of Clay County
# outside them. 320xx also reaches a few North Central Florida counties.
NORTHEAST_FLORIDA_ZIPS = ("320", "322", "32656")
REFRESH_AFTER = 7 * 24 * 3600  # seconds; the directory and indexes change monthly


def in_northeast_florida(zip_code: str) -> bool:
    return (zip_code or "").startswith(NORTHEAST_FLORIDA_ZIPS)


def default_years() -> list[int]:
    """The current and previous index years (see the module docstring)."""
    return [date.today().year - 1, date.today().year]


def _intact(path: Path) -> bool:
    """Is a cached file usable? For a ZIP, truncation is the failure to catch."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    if path.suffix != ".zip":
        return True
    try:
        # Reading the central directory is cheap and fails on a truncated archive.
        with zipfile.ZipFile(path) as archive:
            return bool(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def _download(url: str, destination: Path, *, label: str, max_age: float | None = None) -> Path:
    """Fetch a file, verifying it arrived whole.

    With max_age, a cached copy older than that many seconds is fetched again. If
    that refresh fails, the old copy is kept and used rather than losing a run.

    Size is taken from the GET response, never from a HEAD: irs.gov answers HEAD
    for the master file with a Content-Length of 20 bytes, which would fail every
    check. The server also advertises range support but ignores Range headers, so
    a partial download cannot be resumed - it is discarded and retried.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _intact(destination):
        age = time.time() - destination.stat().st_mtime
        if max_age is None or age < max_age:
            print(f"  cached   {label}  ({destination.stat().st_size / 1_048_576:.1f} MB)")
            return destination
        print(f"  refresh  {label}  (cached copy is {age / 86400:.0f} days old)")
        try:
            return _fetch(url, destination, label=label)
        except (httpx.HTTPError, RuntimeError) as exc:
            print(f"\n  !! could not refresh {label} ({type(exc).__name__}); using the cached copy")
            return destination
    if destination.exists():
        print(f"  re-fetch {label}  (cached copy is empty or truncated)")
    return _fetch(url, destination, label=label)


def _fetch(url: str, destination: Path, *, label: str) -> Path:
    print(f"  download {label} ...", end="", flush=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    written = 0
    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            try:
                expected = int(response.headers.get("Content-Length", 0)) or None
            except ValueError:
                expected = None
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1_048_576):
                    handle.write(chunk)
                    written += len(chunk)
                    if expected:
                        print(f"\r  download {label} ... "
                              f"{min(100, 100 * response.num_bytes_downloaded // expected):>3}%",
                              end="", flush=True)
            # Content-Length counts the bytes on the wire. irs.gov gzips the CSVs,
            # and httpx decompresses as it streams, so the file on disk is larger
            # than Content-Length. num_bytes_downloaded is the raw count to compare.
            received = response.num_bytes_downloaded
    if expected and received != expected:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"{label}: received {received:,} bytes, expected {expected:,}")
    partial.replace(destination)
    if not _intact(destination):
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"{label}: downloaded file is not a readable archive")
    print(f"\r  download {label}  ({written / 1_048_576:.1f} MB)          ")
    return destination


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_ein(value: str) -> str:
    """EINs appear with and without leading zeros across the two IRS files."""
    return (value or "").strip().lstrip("0").zfill(9)


def local_foundations(state: str = "fl", zip_prefixes=NORTHEAST_FLORIDA_ZIPS) -> dict[str, dict]:
    """Step 1. Private foundations headquartered in the configured ZIP codes.

    PF_FILING_REQ_CD == "1" means the organization files a 990-PF, which is the
    only return type that lists individual grants paid.
    """
    path = _download(BMF_URL.format(state=state), CACHE / f"eo_{state}.csv",
                     label=f"{state.upper()} organization directory", max_age=REFRESH_AFTER)
    rows = _read_csv(path)
    foundations = {}
    for row in rows:
        if row.get("PF_FILING_REQ_CD") != "1":
            continue
        if zip_prefixes and not (row.get("ZIP") or "").startswith(tuple(zip_prefixes)):
            continue
        foundations[normalize_ein(row["EIN"])] = row
    print(f"  {len(rows):,} organizations in {state.upper()} "
          f"-> {len(foundations):,} private foundations in the target ZIP codes")
    return foundations


def _newer(row: dict, than: dict | None) -> bool:
    """Latest tax period wins; within a period the later OBJECT_ID (an amendment) wins."""
    if than is None:
        return True
    key = lambda r: (r.get("TAX_PERIOD") or "", int(r.get("OBJECT_ID") or 0))
    return key(row) > key(than)


def filings_for(eins: set[str], years: int | list[int]) -> dict[str, dict]:
    """Step 2. Which of those foundations filed, and which archive holds each filing.

    Each returned row carries YEAR, the index year whose archives hold it.
    """
    years = [years] if isinstance(years, int) else list(years)
    filings: dict[str, dict] = {}
    for year in years:
        try:
            path = _download(INDEX_URL.format(year=year), CACHE / f"index_{year}.csv",
                             label=f"{year} filing index", max_age=REFRESH_AFTER)
        except httpx.HTTPStatusError as exc:
            # Early in January the new year's index may not be published yet.
            if exc.response.status_code == 404 and year != years[0]:
                print(f"  {year} filing index not published yet; skipping")
                continue
            raise
        total = ours = 0
        with path.open(encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                total += 1
                if row.get("RETURN_TYPE") != "990PF":
                    continue
                ein = normalize_ein(row["EIN"])
                if ein not in eins:
                    continue
                ours += 1
                row["YEAR"] = str(year)
                if _newer(row, filings.get(ein)):
                    filings[ein] = row
        print(f"  {total:,} filings in the {year} index -> {ours:,} are ours")
    print(f"  {len(filings):,} foundations with a filing (newest per foundation)")
    return filings


def ensure_archives(filings: dict[str, dict]) -> tuple[dict[str, Path], list[str]]:
    """Step 3. Download only the archives that hold a filing we care about.

    Returns the archive paths and the batches that were newly downloaded.
    """
    batches = sorted({(row["YEAR"], row["XML_BATCH_ID"]) for row in filings.values()})
    print(f"  {len(batches)} archive(s) needed")
    paths, downloaded = {}, []
    for year, batch in batches:
        count = sum(1 for row in filings.values() if row["XML_BATCH_ID"] == batch)
        destination = CACHE / f"{batch}.zip"
        if not _intact(destination):
            downloaded.append(batch)
        paths[batch] = _download(ARCHIVE_URL.format(year=year, batch=batch),
                                 destination, label=f"{batch} ({count} filings)")
    return paths, downloaded


if __name__ == "__main__":
    years = [int(sys.argv[1])] if len(sys.argv) > 1 else default_years()
    foundations = local_foundations()
    filings = filings_for(set(foundations), years)
    ensure_archives(filings)
