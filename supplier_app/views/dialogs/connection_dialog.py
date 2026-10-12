"""Choose where the data lives: this PC (single user) or a PostgreSQL server (several users)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QWidget,
)

from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.settings.connection import MODE_LOCAL, MODE_SERVER, MODE_SHARED, ConnectionConfig, test_connection
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
        self.resize(560, 470)
        root = dialog_root(self)
        intro = QLabel(tr("conn.intro"))
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.local = QRadioButton(tr("conn.local"))
        self.server = QRadioButton(tr("conn.server"))
        self.shared = QRadioButton(tr("conn.shared"))
        root.addWidget(self.local)
        root.addWidget(self.shared)
        shared_row = QHBoxLayout()
        self.shared_path = QLineEdit(config.shared_path)
        self.shared_path.setPlaceholderText(tr("conn.shared.placeholder"))
        self.shared_browse = button(tr("common.browse"), "", self._browse)
        shared_row.addWidget(self.shared_path, 1)
        shared_row.addWidget(self.shared_browse)
        root.addLayout(shared_row)
        self.shared_hint = QLabel(tr("conn.shared.hint"))
        self.shared_hint.setObjectName("Muted")
        self.shared_hint.setWordWrap(True)
        root.addWidget(self.shared_hint)
        root.addWidget(self.server)
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
        self.fields = [self.host, self.port, self.dbname, self.user, self.password, self.save_password, self.ssl]
        root.addLayout(form)
        self.test_btn = button(tr("conn.test"), "", self.test)
        root.addWidget(self.test_btn)
        self.info = message_label()
        root.addWidget(self.info)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self, tr("conn.save")))
        (self.server if config.is_server else self.shared if config.is_shared else self.local).setChecked(True)
        self.local.toggled.connect(self._sync)
        self.shared.toggled.connect(self._sync)
        self._sync()
        if error:
            self.error.setText(error)
            self.error.setVisible(True)

    def _sync(self) -> None:
        on = self.server.isChecked()
        for w in (*self.fields,):
            w.setEnabled(on)
        for w in (self.shared_path, self.shared_browse):
            w.setEnabled(self.shared.isChecked())
        self.test_btn.setEnabled(on or self.shared.isChecked())

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("conn.shared"), self.shared_path.text())
        if folder:
            self.shared_path.setText(folder)

    def _collect(self) -> ConnectionConfig:
        return ConnectionConfig(
            mode=MODE_SERVER if self.server.isChecked() else MODE_SHARED if self.shared.isChecked() else MODE_LOCAL,
            shared_path=self.shared_path.text().strip(), host=self.host.text().strip(), port=self.port.value(),
            dbname=self.dbname.text().strip(), user=self.user.text().strip(), password=self.password.text(),
            sslmode=str(self.ssl.currentData()))

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
