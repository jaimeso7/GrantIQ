"""Step 4: read the grant lists out of a 990-PF filing.

A 990-PF has a section titled "Grants and Contributions Paid During the Year".
In the XML each grant is one <GrantOrContributionPdDurYrGrp> element holding the
recipient, their address, the amount, and - the useful part - the foundation's
own description of what the money was for.

Nothing is inferred. A grant with no stated purpose keeps an empty purpose rather
than borrowing one from elsewhere in the filing.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

# Most IRS archives use ordinary deflate, but some are written with Deflate64,
# which the standard library cannot decompress. Importing this optional package
# patches zipfile to handle it, but it has no prebuilt wheel for every platform
# (none for Python 3.12 on Apple Silicon, and the source build fails there).
# The fallback is the system `unzip` (Info-ZIP 6.0, shipped with macOS), which
# reads Deflate64 natively. Only when neither is available are those archives
# skipped, and the report says so rather than silently returning fewer foundations.
try:  # pragma: no cover - availability depends on the local environment
    import zipfile_deflate64  # noqa: F401
    DEFLATE64_SUPPORTED = True
except ImportError:  # pragma: no cover
    DEFLATE64_SUPPORTED = False

DEFLATE64 = 9
SYSTEM_UNZIP = shutil.which("unzip")
SAFE_MEMBER = re.compile(r"\d+_public\.xml")

# Grants already paid, and grants approved for payment in a future year. The
# second set is a forward-looking commitment, so it is kept but labelled.
PAID = "GrantOrContributionPdDurYrGrp"
APPROVED = "GrantOrContributionApprvFutPmtGrp"


@dataclass
class Gift:
    recipient: str
    city: str
    state: str
    purpose: str
    amount: float | None
    status: str  # "paid" or "approved"
    zip: str = ""  # recipient ZIP code, used to tell where a foundation gives


@dataclass
class Filing:
    ein: str
    name: str
    tax_period: str
    object_id: str
    gifts: list[Gift] = field(default_factory=list)

    @property
    def total_paid(self) -> float:
        return sum(g.amount or 0 for g in self.gifts if g.status == "paid")

    @property
    def paid_count(self) -> int:
        return sum(1 for g in self.gifts if g.status == "paid")


def _tag(element) -> str:
    """Local element name, ignoring the XML namespace (it changes by filing year)."""
    return element.tag.rsplit("}", 1)[-1]


def _first_text(element, *names: str) -> str:
    """First non-empty descendant text matching any of these local tag names."""
    for name in names:
        for child in element.iter():
            if _tag(child) == name and (child.text or "").strip():
                return " ".join(child.text.split())
    return ""


def _amount(element) -> float | None:
    raw = _first_text(element, "Amt")
    try:
        return float(raw.replace(",", "").replace("$", "")) if raw else None
    except ValueError:
        return None


def _gift(group, status: str) -> Gift:
    return Gift(
        # Organizations use RecipientBusinessName; individuals use RecipientPersonNm.
        recipient=_first_text(group, "BusinessNameLine1Txt", "RecipientPersonNm"),
        city=_first_text(group, "CityNm"),
        state=_first_text(group, "StateAbbreviationCd"),
        purpose=_first_text(group, "GrantOrContributionPurposeTxt"),
        amount=_amount(group),
        status=status,
        zip=_first_text(group, "ZIPCd")[:5],
    )


def _system_unzip(path: Path, names: list[str]) -> dict[str, bytes]:
    """Extract many members in one system unzip call, for compression zipfile lacks.

    One call per archive, not per filing: unzip re-reads the whole central
    directory (80,000+ entries) on every run. The IRS archives make unzip warn
    about "extra bytes" and exit non-zero, yet it still writes the members
    intact, so success is judged by which files appear, not by the exit code.
    """
    # IRS members are always "<digits>_public.xml". Refusing anything else keeps a
    # malformed archive from passing an option ("-...") or a path ("../") to unzip.
    names = [name for name in names if SAFE_MEMBER.fullmatch(name)]
    if not SYSTEM_UNZIP or not names:
        return {}
    with tempfile.TemporaryDirectory(prefix="irs990-") as folder:
        for start in range(0, len(names), 500):  # stay well under the command-line limit
            subprocess.run([SYSTEM_UNZIP, "-o", "-qq", str(path), *names[start:start + 500], "-d", folder],
                           capture_output=True, check=False)
        return {name: (Path(folder) / name).read_bytes() for name in names if (Path(folder) / name).is_file()}


def read_filing(archive: zipfile.ZipFile, object_id: str, extracted: dict[str, bytes] | None = None,
                names: set[str] | None = None) -> Filing | None:
    """Parse one filing out of an archive without extracting the whole thing."""
    name = f"{object_id}_public.xml"
    names = names if names is not None else set(archive.namelist())
    if name not in names:
        name = next((n for n in names if n.startswith(object_id)), None)
        if name is None:
            return None
    payload = (extracted or {}).get(name)
    if payload is None:
        try:
            payload = archive.read(name)
        except NotImplementedError:
            # Deflate64 member, no optional decoder, and it was not pre-extracted.
            extracted_one = _system_unzip(Path(archive.filename), [name]) if archive.filename else {}
            payload = extracted_one.get(name)
    if payload is None:
        return None
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return None

    header = next((e for e in root.iter() if _tag(e) == "Filer"), root)
    filing = Filing(
        ein=_first_text(header, "EIN"),
        name=_first_text(header, "BusinessNameLine1Txt", "Name"),
        tax_period=_first_text(root, "TaxPeriodEndDt", "TaxPeriodEndDate"),
        object_id=object_id,
    )
    for element in root.iter():
        tag = _tag(element)
        if tag == PAID:
            filing.gifts.append(_gift(element, "paid"))
        elif tag == APPROVED:
            filing.gifts.append(_gift(element, "approved"))
    return filing


def read_filings(archive_paths: dict[str, Path], filings: dict[str, dict]) -> list[Filing]:
    """Parse every target filing, grouping work by archive so each opens once."""
    by_batch: dict[str, list[tuple[str, dict]]] = {}
    for ein, row in filings.items():
        by_batch.setdefault(row["XML_BATCH_ID"], []).append((ein, row))

    parsed, missing, unsupported = [], 0, {}
    for batch, entries in sorted(by_batch.items()):
        path = archive_paths.get(batch)
        if not path or not path.exists():
            missing += len(entries)
            continue
        with zipfile.ZipFile(path) as archive:
            deflate64 = any(info.compress_type == DEFLATE64 for info in archive.infolist()[:1])
            if deflate64 and not DEFLATE64_SUPPORTED and not SYSTEM_UNZIP:
                unsupported[batch] = len(entries)
                continue
            names = set(archive.namelist())
            extracted = {}
            if deflate64 and not DEFLATE64_SUPPORTED:
                extracted = _system_unzip(path, [n for n in (f"{row['OBJECT_ID']}_public.xml" for _, row in entries)
                                                 if n in names])
            for ein, row in entries:
                filing = read_filing(archive, row["OBJECT_ID"], extracted, names)
                if filing is None:
                    missing += 1
                    continue
                if not filing.ein:
                    filing.ein = ein
                parsed.append(filing)

    with_gifts = sum(1 for f in parsed if f.paid_count)
    print(f"  parsed {len(parsed):,} filings ({missing} unreadable); "
          f"{with_gifts:,} list at least one grant paid")
    if unsupported:
        skipped = sum(unsupported.values())
        print(f"\n  !! {skipped} filings in {len(unsupported)} archive(s) were SKIPPED: they use")
        print("     Deflate64 compression, which Python's zipfile cannot read, and no")
        print("     system `unzip` was found to fall back on.")
        for batch, count in sorted(unsupported.items()):
            print(f"       {batch}  ({count} filings)")
        print("     To include them, install Info-ZIP unzip or the zipfile-deflate64 package.")
        print("     Results below are complete for every other archive.\n")
    return parsed
