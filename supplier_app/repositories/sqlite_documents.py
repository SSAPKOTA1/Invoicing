"""SQLite implementations of document, reference and case repositories."""

from __future__ import annotations

import re
import sqlite3

from supplier_app.errors import DatabaseError, DuplicateError, NotFoundError, ValidationError
from supplier_app.models.entities import Case, CaseEvent, Document, DocumentReference
from supplier_app.models.enums import CaseStatus, DocumentType, ReferenceType, ReviewStatus
from supplier_app.repositories.interfaces import CaseRepository, DocumentRepository, ReferenceRepository
from supplier_app.repositories.sqlite_base import SqliteRepo, d2s, like_escape, must_date, stamp


def _document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"], stored_path=row["stored_path"], sha256=row["sha256"], original_name=row["original_name"],
        page_count=row["page_count"], doc_type=DocumentType(row["doc_type"]), ocr_text=row["ocr_text"],
        extraction_json=row["extraction_json"], review_status=ReviewStatus(row["review_status"]),
        confidence=row["confidence"], supplier_id=row["supplier_id"], text_source=row["text_source"],
        created_at=row["created_at"],
    )


class SqliteDocumentRepository(SqliteRepo, DocumentRepository):
    def add(self, doc: Document) -> Document:
        doc.created_at = stamp(doc.created_at)
        try:
            doc.id = self.db.insert(
                "INSERT INTO documents(stored_path, sha256, original_name, page_count, doc_type, ocr_text,"
                " extraction_json, review_status, confidence, supplier_id, text_source, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc.stored_path, doc.sha256, doc.original_name, doc.page_count, doc.doc_type.value, doc.ocr_text,
                 doc.extraction_json, doc.review_status.value, doc.confidence, doc.supplier_id, doc.text_source,
                 doc.created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError("Dieses Dokument wurde bereits importiert (gleicher Hash).") from exc
        return doc

    def get(self, doc_id: int) -> Document | None:
        row = self.db.query_one("SELECT * FROM documents WHERE id=?", (doc_id,))
        return _document(row) if row else None

    def get_by_hash(self, sha256: str) -> Document | None:
        row = self.db.query_one("SELECT * FROM documents WHERE sha256=?", (sha256,))
        return _document(row) if row else None

    def update(self, doc: Document) -> None:
        if doc.id is None:
            raise NotFoundError("Dokument ohne ID.")
        self.db.execute(
            "UPDATE documents SET stored_path=?, original_name=?, page_count=?, doc_type=?, ocr_text=?,"
            " extraction_json=?, review_status=?, confidence=?, supplier_id=?, text_source=? WHERE id=?",
            (doc.stored_path, doc.original_name, doc.page_count, doc.doc_type.value, doc.ocr_text,
             doc.extraction_json, doc.review_status.value, doc.confidence, doc.supplier_id, doc.text_source, doc.id),
        )

    def list(
        self, *, review_status: ReviewStatus | None = None, supplier_id: int | None = None, limit: int | None = None
    ) -> list[Document]:
        sql, params = "SELECT * FROM documents WHERE 1=1", []
        if review_status is not None:
            sql += " AND review_status=?"
            params.append(review_status.value)
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        sql += " ORDER BY id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [_document(r) for r in self.db.query_all(sql, params)]

    def fulltext(self, fts_query: str, limit: int = 50) -> list[tuple[int, str]]:
        try:
            rows = self.db.query_all(
                "SELECT rowid, snippet(document_fts, 1, '[', ']', ' … ', 12) FROM document_fts"
                " WHERE document_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit),
            )
        except DatabaseError as exc:
            raise ValidationError("Ungültige Suchanfrage.") from exc
        return [(r[0], r[1]) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.db.query_all("SELECT review_status, COUNT(*) FROM documents GROUP BY 1")}


class SqliteReferenceRepository(SqliteRepo, ReferenceRepository):
    @staticmethod
    def _ref(row: sqlite3.Row) -> DocumentReference:
        return DocumentReference(
            id=row["id"], owner_kind=row["owner_kind"], owner_id=row["owner_id"],
            ref_type=ReferenceType(row["ref_type"]), raw_value=row["raw_value"],
            normalized_value=row["normalized_value"],
        )

    def add(self, ref: DocumentReference) -> DocumentReference | None:
        try:
            ref.id = self.db.insert(
                "INSERT INTO document_references(owner_kind, owner_id, ref_type, raw_value, normalized_value,"
                " created_at) VALUES (?,?,?,?,?,?)",
                (ref.owner_kind, ref.owner_id, ref.ref_type.value, ref.raw_value, ref.normalized_value, stamp("")),
            )
        except sqlite3.IntegrityError:
            return None
        return ref

    def for_owner(self, owner_kind: str, owner_id: int) -> list[DocumentReference]:
        rows = self.db.query_all(
            "SELECT * FROM document_references WHERE owner_kind=? AND owner_id=? ORDER BY id", (owner_kind, owner_id)
        )
        return [self._ref(r) for r in rows]

    def find(self, normalized: str, *, prefix: bool = False) -> list[DocumentReference]:
        if not normalized:
            return []
        if prefix:
            rows = self.db.query_all(
                "SELECT * FROM document_references WHERE normalized_value LIKE ? ESCAPE '\\' ORDER BY id",
                (f"%{like_escape(normalized)}%",),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM document_references WHERE normalized_value=? ORDER BY id", (normalized,)
            )
        return [self._ref(r) for r in rows]


def _case(row: sqlite3.Row) -> Case:
    return Case(
        id=row["id"], supplier_id=row["supplier_id"], invoice_id=row["invoice_id"], title=row["title"],
        status=CaseStatus(row["status"]), notes=row["notes"], opened_at=row["opened_at"],
        auto_opened=bool(row["auto_opened"]),
    )


class SqliteCaseRepository(SqliteRepo, CaseRepository):
    def add(self, case: Case) -> Case:
        case.opened_at = stamp(case.opened_at)
        try:
            case.id = self.db.insert(
                "INSERT INTO cases(supplier_id, invoice_id, title, status, notes, auto_opened, opened_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (case.supplier_id, case.invoice_id, case.title, case.status.value, case.notes,
                 int(case.auto_opened), case.opened_at),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError("Für diese Rechnung existiert bereits ein Vorgang.") from exc
        return case

    def get(self, case_id: int) -> Case | None:
        row = self.db.query_one("SELECT * FROM cases WHERE id=?", (case_id,))
        return _case(row) if row else None

    def get_by_invoice(self, invoice_id: int) -> Case | None:
        row = self.db.query_one("SELECT * FROM cases WHERE invoice_id=?", (invoice_id,))
        return _case(row) if row else None

    def update(self, case: Case) -> None:
        closed = stamp("") if case.status == CaseStatus.CLOSED else None
        self.db.execute(
            "UPDATE cases SET title=?, status=?, notes=?, closed_at=? WHERE id=?",
            (case.title, case.status.value, case.notes, closed, case.id),
        )

    def list(self, *, supplier_id: int | None = None, status: str | None = None) -> list[Case]:
        sql, params = "SELECT * FROM cases WHERE 1=1", []
        if supplier_id is not None:
            sql += " AND supplier_id=?"
            params.append(supplier_id)
        if status is not None:
            sql += " AND status=?"
            params.append(status)
        return [_case(r) for r in self.db.query_all(sql + " ORDER BY id DESC", params)]

    def add_event(self, event: CaseEvent) -> CaseEvent:
        event.created_at = stamp(event.created_at)
        event.id = self.db.insert(
            "INSERT INTO case_events(case_id, event_date, kind, text, created_at) VALUES (?,?,?,?,?)",
            (event.case_id, d2s(event.event_date), event.kind, event.text, event.created_at),
        )
        return event

    def events(self, case_id: int) -> list[CaseEvent]:
        rows = self.db.query_all("SELECT * FROM case_events WHERE case_id=? ORDER BY event_date, id", (case_id,))
        return [
            CaseEvent(id=r["id"], case_id=r["case_id"], event_date=must_date(r["event_date"]), kind=r["kind"],
                      text=r["text"], created_at=r["created_at"])
            for r in rows
        ]


def fts_query_from_text(text: str) -> str:
    """Turn free user text into a safe FTS5 prefix query (``abc def -> "abc"* "def"*``)."""
    tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)
    return " ".join(f'"{t}"*' for t in tokens)
