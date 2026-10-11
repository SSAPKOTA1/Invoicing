"""Where is the PostgreSQL server? Server, database, user and password; with a connection test."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLabel, QLineEdit, QSpinBox, QWidget

from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.settings.connection import ConnectionConfig, test_connection
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.widgets.common import button


class ConnectionDialog(QDialog):
    """Edits a :class:`ConnectionConfig`; ``result_config`` holds the accepted settings."""

    def __init__(self, config: ConnectionConfig, parent: QWidget | None = None, error: str = "") -> None:
        super().__init__(parent)
        self.config = config
        self.result_config: ConnectionConfig | None = None
        self.setWindowTitle(tr("conn.title"))
        self.setModal(True)
        self.resize(560, 420)
        root = dialog_root(self)
        intro = QLabel(tr("conn.intro"))
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        root.addWidget(intro)
        form = form_layout()
        self.host = QLineEdit(config.host)
        self.host.setPlaceholderText(tr("conn.host.placeholder"))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(config.port)
        self.dbname = QLineEdit(config.dbname)
        self.user = QLineEdit(config.user)
        self.password = QLineEdit(config.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.save_password = QCheckBox(tr("conn.save_password"))
        self.save_password.setChecked(True)
        self.ssl = QComboBox()
        for mode, text in (("prefer", tr("conn.ssl.prefer")), ("require", tr("conn.ssl.require")), ("disable", tr("conn.ssl.disable"))):
            self.ssl.addItem(text, mode)
        self.ssl.setCurrentIndex(max(0, self.ssl.findData(config.sslmode)))
        form.addRow(tr("conn.host"), self.host)
        form.addRow(tr("conn.port"), self.port)
        form.addRow(tr("conn.dbname"), self.dbname)
        form.addRow(tr("conn.user"), self.user)
        form.addRow(tr("conn.password"), self.password)
        form.addRow("", self.save_password)
        form.addRow(tr("conn.ssl"), self.ssl)
        root.addLayout(form)
        root.addWidget(button(tr("conn.test"), "", self.test))
        self.info = message_label()
        root.addWidget(self.info)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self, tr("conn.save")))
        if error:
            self.error.setText(error)
            self.error.setVisible(True)
        (self.password if self.host.text() else self.host).setFocus()

    def _collect(self) -> ConnectionConfig:
        return ConnectionConfig(
            host=self.host.text().strip(), port=self.port.value(), dbname=self.dbname.text().strip(),
            user=self.user.text().strip(), password=self.password.text(), sslmode=str(self.ssl.currentData()))

    def test(self) -> None:
        self.error.setVisible(False)
        self.info.setVisible(False)
        cfg = self._collect()
        try:
            cfg.validate()
            version = test_connection(cfg)
        except SupplierAppError as exc:
            self.error.setText(exc.message + (f"\n{exc.hint}" if exc.hint else ""))
            self.error.setVisible(True)
            return
        self.info.setText(tr("conn.test.ok", version=version))
        self.info.setVisible(True)

    def accept(self) -> None:
        cfg = self._collect()
        try:
            cfg.validate()
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        self.keep_password = self.save_password.isChecked()
        self.result_config = cfg
        super().accept()

    keep_password = True
