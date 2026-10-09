"""Custom exception hierarchy. User-facing messages are German."""

from __future__ import annotations


class SupplierAppError(Exception):
    """Base class for all application errors; the message is safe to show to the user."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message


class DatabaseError(SupplierAppError):
    """Problems opening, locking or migrating the database."""


class MigrationError(DatabaseError):
    """A migration failed; the database was restored from backup."""


class NotFoundError(SupplierAppError):
    """An entity does not exist."""


class ValidationError(SupplierAppError):
    """Invalid user input or inconsistent data."""


class LedgerError(SupplierAppError):
    """A ledger rule would be violated."""


class DuplicateError(SupplierAppError):
    """The entity (or document) already exists."""


class OcrError(SupplierAppError):
    """Text extraction failed."""


class TesseractMissingError(OcrError):
    """Tesseract could not be found."""


class DocumentError(SupplierAppError):
    """A file cannot be read (corrupt, unsupported, too large)."""


class BackupError(SupplierAppError):
    """Backup or restore failed."""


class AuthError(SupplierAppError):
    """PIN problems (wrong PIN, locked out)."""
