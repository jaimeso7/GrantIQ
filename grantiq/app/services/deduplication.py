import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    query = sorted((k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"})
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(query), ""))

def normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()).strip()

def fingerprint(record) -> str:
    # Unknown funders/deadlines are insufficient evidence for cross-source identity.
    if record.funder_name == "Unknown" or record.deadline is None:
        key = f"{record.source}|{record.source_id}"
    else:
        key = f"{normalized_text(record.grant_title)}|{normalized_text(record.funder_name)}|{record.deadline.isoformat()}"
    return hashlib.sha256(key.encode()).hexdigest()
