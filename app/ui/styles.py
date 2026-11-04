WINDOW_STYLE = """
QMainWindow, QWidget#workspace { background: #f6f7f9; color: #202631; }
QLabel#brand { font-size: 18px; font-weight: 700; color: #182230; }
QLabel#pageTitle { font-size: 23px; font-weight: 700; color: #182230; }
QLabel#taskStatus { color: #526275; }
QPushButton {
    padding: 5px 9px; border: 1px solid #d7dde5; border-radius: 5px;
    background: #ffffff; color: #243143;
}
QPushButton:hover { background: #ecf2f8; }
QPushButton:disabled { background: #edf0f4; color: #647083; }
QPushButton[nav="true"] { text-align: left; background: transparent; border-color: transparent; }
QPushButton[nav="true"]:hover { background: #e8eef5; }
QPushButton[nav="true"]:checked { background: #dceaf9; color: #163d69; font-weight: 700; }
QPushButton[kind="primary"]:enabled { background: #245d9d; color: white; border-color: #245d9d; }
QPushButton[kind="danger"]:enabled { background: #fff4ee; color: #8c3523; border-color: #d8a69a; }
QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit {
    padding: 4px; border: 1px solid #d7dde5; border-radius: 5px; background: white;
}
QTableView, QTreeWidget { background: white; alternate-background-color: #f7f9fb;
    border: 1px solid #dce2e9; border-radius: 5px;
    selection-background-color: #daeafa; selection-color: #182230;
}
QHeaderView::section { padding: 5px; background: #edf1f5; border: 0;
    border-right: 1px solid #e0e5ec; color: #28374b; }
"""
