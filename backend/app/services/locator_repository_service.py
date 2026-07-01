"""Ingests uploaded locator repository files into versioned `LocatorEntry` rows.

Every upload for a given transaction number creates a new `LocatorRepositoryVersion`
(auto-incrementing per transaction) and deactivates whichever version was previously
active for that transaction — so "rolling back" is just reactivating an older
version, and the currently-active version is always what `locator_resolver` prefers.
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from app.agents.java_po_parser import parse_java_po
from app.agents.locator_file_parsers import parse_locator_file
from app.models.locator import LocatorEntry
from app.models.locator_version import LocatorRepositoryVersion


def _extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"


def _ingest_rows(
    db: Session,
    rows: list[dict],
    filename: str,
    source_format: str,
) -> list[LocatorRepositoryVersion]:
    """Core ingestion: takes already-parsed rows and writes version + entry rows."""
    rows_by_transaction: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        rows_by_transaction[row["transaction_number"]].append(row)

    created_versions = []
    for transaction_number, txn_rows in rows_by_transaction.items():
        previous_max = (
            db.query(LocatorRepositoryVersion)
            .filter(LocatorRepositoryVersion.transaction_number == transaction_number)
            .order_by(LocatorRepositoryVersion.version_number.desc())
            .first()
        )
        next_version_number = (previous_max.version_number + 1) if previous_max else 1

        db.query(LocatorRepositoryVersion).filter(
            LocatorRepositoryVersion.transaction_number == transaction_number
        ).update({"is_active": False})

        version = LocatorRepositoryVersion(
            transaction_number=transaction_number,
            version_number=next_version_number,
            is_active=True,
            source_filename=filename,
            source_format=source_format,
        )
        db.add(version)
        db.flush()
        created_versions.append(version)

        for row in txn_rows:
            db.add(
                LocatorEntry(
                    version_id=version.id,
                    source="upload",
                    transaction_number=transaction_number,
                    screen_name=row["screen_name"],
                    field_name=row["field_name"],
                    priority_locator=row["priority_locator"],
                    priority_locator_type=row.get("priority_locator_type", "css"),
                    fallback_locator=row.get("fallback_locator"),
                    fallback_locator_type=row.get("fallback_locator_type"),
                    ai_confidence_score=row.get("ai_confidence_score", 0.8),
                    is_mandatory=row.get("is_mandatory", False),
                    control_type=row.get("control_type", "text_input"),
                )
            )

    db.commit()
    return created_versions


def ingest_locator_file(db: Session, filename: str, raw_bytes: bytes) -> list[LocatorRepositoryVersion]:
    rows = parse_locator_file(filename, raw_bytes)
    return _ingest_rows(db, rows, filename, _extension_of(filename))


def ingest_java_po_file(
    db: Session,
    filename: str,
    raw_bytes: bytes,
    transaction_number: str,
    screen_name: str,
) -> list[LocatorRepositoryVersion]:
    source = raw_bytes.decode("utf-8", errors="replace")
    rows = parse_java_po(source, transaction_number, screen_name)
    if not rows:
        raise ValueError(f"No By.id/By.xpath locators found in {filename}")
    return _ingest_rows(db, rows, filename, "java_po")


def list_versions(db: Session, transaction_number: str) -> list[LocatorRepositoryVersion]:
    return (
        db.query(LocatorRepositoryVersion)
        .filter(LocatorRepositoryVersion.transaction_number == transaction_number)
        .order_by(LocatorRepositoryVersion.version_number.desc())
        .all()
    )


def set_active_version(db: Session, transaction_number: str, version_id: str) -> LocatorRepositoryVersion:
    version = db.get(LocatorRepositoryVersion, version_id)
    if version is None or version.transaction_number != transaction_number:
        raise ValueError("Version not found for this transaction")

    db.query(LocatorRepositoryVersion).filter(
        LocatorRepositoryVersion.transaction_number == transaction_number
    ).update({"is_active": False})
    version.is_active = True
    db.commit()
    return version


def merge_versions(db: Session, transaction_number: str, version_ids: list[str]) -> LocatorRepositoryVersion:
    """Unions the entries of the given versions into one new version. On a field-name
    conflict (the same field defined in more than one of the selected versions), the
    entry from the highest source version number wins — newer data takes precedence,
    same as the layered resolution chain in `locator_resolver`."""
    versions = (
        db.query(LocatorRepositoryVersion)
        .filter(LocatorRepositoryVersion.id.in_(version_ids))
        .all()
    )
    if len(versions) != len(set(version_ids)):
        raise ValueError("One or more version IDs were not found")
    if any(v.transaction_number != transaction_number for v in versions):
        raise ValueError("All versions to merge must belong to the given transaction number")

    version_number_by_id = {v.id: v.version_number for v in versions}
    entries = db.query(LocatorEntry).filter(LocatorEntry.version_id.in_(version_ids)).all()

    by_field: dict[str, list[LocatorEntry]] = {}
    for entry in entries:
        by_field.setdefault(entry.field_name.strip().lower(), []).append(entry)

    winners = [
        max(field_entries, key=lambda e: version_number_by_id[e.version_id]) for field_entries in by_field.values()
    ]

    previous_max = (
        db.query(LocatorRepositoryVersion)
        .filter(LocatorRepositoryVersion.transaction_number == transaction_number)
        .order_by(LocatorRepositoryVersion.version_number.desc())
        .first()
    )
    next_version_number = previous_max.version_number + 1

    db.query(LocatorRepositoryVersion).filter(
        LocatorRepositoryVersion.transaction_number == transaction_number
    ).update({"is_active": False})

    merged_version = LocatorRepositoryVersion(
        transaction_number=transaction_number,
        version_number=next_version_number,
        is_active=True,
        source_filename=f"merged({','.join(v.source_filename for v in versions)})",
        source_format="merged",
    )
    db.add(merged_version)
    db.flush()

    for winner in winners:
        db.add(
            LocatorEntry(
                version_id=merged_version.id,
                source="upload",
                transaction_number=transaction_number,
                screen_name=winner.screen_name,
                field_name=winner.field_name,
                priority_locator=winner.priority_locator,
                priority_locator_type=winner.priority_locator_type,
                fallback_locator=winner.fallback_locator,
                fallback_locator_type=winner.fallback_locator_type,
                ai_confidence_score=winner.ai_confidence_score,
                is_mandatory=winner.is_mandatory,
                control_type=winner.control_type,
            )
        )

    db.commit()
    return merged_version
