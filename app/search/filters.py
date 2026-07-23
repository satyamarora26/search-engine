from datetime import UTC, date, datetime
from urllib.parse import urlsplit


def normalize_source(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().rstrip(".")
    return normalized or None


def derive_source_host(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None

    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return None

    if not hostname:
        return None
    return hostname.lower().rstrip(".") or None


def created_at_utc_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(UTC).date()


def matches_metadata(
    document_source: str | None,
    document_created_at: datetime | None,
    source: str | None,
    created_from: date | None,
    created_to: date | None,
) -> bool:
    normalized_source = normalize_source(source)
    if normalized_source is not None:
        normalized_document_source = normalize_source(document_source)
        if normalized_document_source is None or not (
            normalized_document_source == normalized_source
            or normalized_document_source.endswith(f".{normalized_source}")
        ):
            return False

    if created_from is None and created_to is None:
        return True

    document_date = created_at_utc_date(document_created_at)
    if document_date is None:
        return False
    if created_from is not None and document_date < created_from:
        return False
    if created_to is not None and document_date > created_to:
        return False
    return True
