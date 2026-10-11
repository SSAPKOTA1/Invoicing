"""Login, first administrator, password change and user dialogs of the multi-user mode."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLabel, QLineEdit, QWidget

from supplier_app.errors import SupplierAppError
from supplier_app.i18n import tr
from supplier_app.models.entities import AppUser
from supplier_app.models.enums import UserRole
from supplier_app.services.user_service import UserService
from supplier_app.views.dialogs.forms import button_box, dialog_root, form_layout, message_label
from supplier_app.views.widgets.common import button


def _password_edit() -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    return e


class LoginDialog(QDialog):
    """Sign in. ``fixed_user`` turns it into the lock screen of the running session (password only)."""

    def __init__(self, users: UserService, server_label: str = "", fixed_user: str = "", last_user: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.users = users
        self.fixed_user = fixed_user
        self.user: AppUser | None = None
        self.change_connection = False
        self.setWindowTitle(tr("login.unlock.title") if fixed_user else tr("login.title"))
        self.setModal(True)
        self.resize(420, 260)
        root = dialog_root(self)
        title = QLabel(tr("login.unlock.text") if fixed_user else tr("login.text"))
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        if server_label:
            where = QLabel(tr("login.server", server=server_label))
            where.setObjectName("Muted")
            root.addWidget(where)
        form = form_layout()
        self.username = QLineEdit(fixed_user or last_user)
        self.username.setReadOnly(bool(fixed_user))
        self.password = _password_edit()
        self.password.returnPressed.connect(self.accept)
        form.addRow(tr("login.username"), self.username)
        form.addRow(tr("login.password"), self.password)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self, tr("login.button")))
        if server_label and not fixed_user:
            root.addWidget(button(tr("login.change_connection"), "", self._change_connection))
        (self.password if self.username.text() else self.username).setFocus()

    def _change_connection(self) -> None:
        self.change_connection = True
        self.reject()

    def accept(self) -> None:
        try:
            # the lock screen only verifies the password; a real login starts the session
            self.user = (self.users.verify if self.fixed_user else self.users.login)(self.username.text(), self.password.text())
        except SupplierAppError as exc:
            self.password.clear()
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        super().accept()


class FirstAdminDialog(QDialog):
    """The server database has no users yet: create the administrator."""

    def __init__(self, users: UserService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.users = users
        self.setWindowTitle(tr("login.first.title"))
        self.setModal(True)
        self.resize(460, 330)
        root = dialog_root(self)
        title = QLabel(tr("login.first.text"))
        title.setObjectName("Muted")
        title.setWordWrap(True)
        root.addWidget(title)
        form = form_layout()
        self.username = QLineEdit("admin")
        self.display = QLineEdit()
        self.password, self.repeat = _password_edit(), _password_edit()
        form.addRow(tr("login.username"), self.username)
        form.addRow(tr("user.display_name"), self.display)
        form.addRow(tr("login.password"), self.password)
        form.addRow(tr("login.repeat"), self.repeat)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self, tr("login.first.button")))

    def accept(self) -> None:
        if self.password.text() != self.repeat.text():
            self.error.setText(tr("login.mismatch"))
            self.error.setVisible(True)
            return
        try:
            admin = self.users.create_user(self.username.text(), self.password.text(), UserRole.ADMIN, self.display.text())
            self.users.login(admin.username, self.password.text())
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        super().accept()


class PasswordDialog(QDialog):
    """Change the own password (``own=True``) or set a new one for a colleague (administrator)."""

    def __init__(self, users: UserService, user_id: int, own: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.users, self.user_id, self.own = users, user_id, own
        self.setWindowTitle(tr("user.password.change") if own else tr("user.password.reset"))
        self.resize(420, 260)
        root = dialog_root(self)
        form = form_layout()
        self.current = _password_edit()
        self.new, self.repeat = _password_edit(), _password_edit()
        if own:
            form.addRow(tr("user.password.current"), self.current)
        form.addRow(tr("user.password.new"), self.new)
        form.addRow(tr("login.repeat"), self.repeat)
        root.addLayout(form)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self))

    def accept(self) -> None:
        if self.new.text() != self.repeat.text():
            self.error.setText(tr("login.mismatch"))
            self.error.setVisible(True)
            return
        try:
            if self.own:
                self.users.change_password(self.user_id, self.current.text(), self.new.text())
            else:
                self.users.reset_password(self.user_id, self.new.text())
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        super().accept()


class UserDialog(QDialog):
    """New user (administrator) or edit role / name / active flag."""

    def __init__(self, users: UserService, user: AppUser | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.users, self.user = users, user
        self.setWindowTitle(tr("user.edit") if user else tr("user.new"))
        self.resize(440, 340)
        root = dialog_root(self)
        form = form_layout()
        self.username = QLineEdit(user.username if user else "")
        self.username.setReadOnly(user is not None)
        self.display = QLineEdit(user.display_name if user else "")
        self.role = QComboBox()
        for r in UserRole:
            self.role.addItem(tr(f"role.user.{r.value}"), r)
        self.role.setCurrentIndex(self.role.findData(user.role if user else UserRole.EDITOR))
        self.active = QCheckBox(tr("user.active"))
        self.active.setChecked(user.active if user else True)
        self.password, self.repeat = _password_edit(), _password_edit()
        form.addRow(tr("login.username"), self.username)
        form.addRow(tr("user.display_name"), self.display)
        form.addRow(tr("user.role"), self.role)
        if user is None:
            form.addRow(tr("login.password"), self.password)
            form.addRow(tr("login.repeat"), self.repeat)
        else:
            form.addRow("", self.active)
        root.addLayout(form)
        hint = QLabel(tr("user.role.hint"))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.error = message_label(danger=True)
        root.addWidget(self.error)
        root.addWidget(button_box(self))

    def accept(self) -> None:
        try:
            role = UserRole(self.role.currentData())
            if self.user is None:
                if self.password.text() != self.repeat.text():
                    raise SupplierAppError(tr("login.mismatch"))
                self.users.create_user(self.username.text(), self.password.text(), role, self.display.text())
            else:
                assert self.user.id is not None
                self.users.update_user(self.user.id, role=role, display_name=self.display.text(), active=self.active.isChecked())
        except SupplierAppError as exc:
            self.error.setText(exc.message)
            self.error.setVisible(True)
            return
        super().accept()
