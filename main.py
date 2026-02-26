import sys
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple
import urllib.parse
import requests
from bs4 import BeautifulSoup
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QListWidget, QListWidgetItem,
    QLabel, QTabWidget, QHBoxLayout, QLineEdit,
    QComboBox, QSpinBox, QMessageBox,
    QDialog, QTextEdit, QFormLayout, QStackedWidget,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor

SOURCES_FILE = "sources.json"
BASE_URL = "https://raspisanie.rusoil.net/rasp_old/"

@dataclass
class Lesson:
    date: str
    pair: str
    discipline: str
    type: str
    owner: str
    priority: int

@dataclass
class Source:
    name: str
    search_type: str
    query: str
    priority: int
    enabled: bool

def load_sources():
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [Source(**item) for item in data]
    except:
        return []

def save_sources(sources):
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in sources], f, indent=4, ensure_ascii=False)

def build_url(source: Source):
    q = urllib.parse.quote_plus(source.query)
    if source.search_type == "group":
        return f"{BASE_URL}index.php?gruppa={q}&sem=0"
    else:
        return f"{BASE_URL}index.php?family={q}&sem=0"


def _decode_schedule_html(raw: bytes) -> str:
    """Декодирует HTML расписания (сайт может отдавать UTF-8 или cp1251)."""
    for enc in ("utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            if "День недели" in text or "расписан" in text.lower():
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _fetch_page(url: str, source: Source, use_post: bool) -> Tuple[str, int]:
    """Возвращает (html_text, status_code)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    if use_post:
        data = {"sem": "0"}
        if source.search_type == "group":
            data["gruppa"] = source.query
        else:
            data["family"] = source.query
        r = requests.post(url, data=data, timeout=15, headers=headers)
    else:
        r = requests.get(url, timeout=15, headers=headers)
    html = _decode_schedule_html(r.content)
    return html, r.status_code

def _parse_schedule_table(soup: BeautifulSoup, source: Source):
    """Парсит таблицу расписания: День недели | Пара 1-7 | ячейка с несколькими занятиями."""
    lessons = []
    # Ищем таблицу, в которой есть заголовок «День недели» (в первой строке или в любом месте)
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 5:
            continue
        table_text = table.get_text()
        if "День недели" not in table_text:
            continue
        first_row_cells = rows[0].find_all(["th", "td"])
        first_row_text = " ".join(c.get_text(strip=True) for c in first_row_cells)
        if "День недели" not in first_row_text:
            continue

        current_day = ""
        for tr in rows[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            if len(cells) == 3:
                current_day = cells[0].get_text(strip=True)
                pair_num = cells[1].get_text(strip=True)
                content_cell = cells[2]
            else:
                pair_num = cells[0].get_text(strip=True)
                content_cell = cells[1]

            pair_num = pair_num.replace("\n", "").strip()
            if not pair_num.isdigit():
                continue
            if len(cells) == 2 and not current_day:
                continue

            raw = content_cell.get_text(separator="\n")
            lines = [s.strip() for s in raw.split("\n") if s.strip() and s.strip() != "&nbsp;"]

            for line in lines:
                if len(line) < 5:
                    continue
                # Формат: ...Дисциплина(Л|П|лаб|сем) Преподаватель место — пробела перед скобкой может не быть
                m = re.search(r"\((Л|П|лаб|сем)\)\s+(.+)$", line)
                if not m:
                    continue
                lesson_type = m.group(1)
                rest = line[: m.start()].strip()
                discipline = re.sub(r"^\d+(?:\s*-\s*\d+)?(?:\s*\(\d+\))?\s+", "", rest).strip()
                if not discipline:
                    discipline = rest
                lessons.append(
                    Lesson(
                        date=current_day,
                        pair=pair_num,
                        discipline=discipline,
                        type=lesson_type,
                        owner=source.query,
                        priority=source.priority,
                    )
                )
        if lessons:
            break
    return lessons


def fetch_schedule(source: Source, save_debug_html: bool = False):
    logs = []
    url = build_url(source)
    logs.append(f"Запрос: {url}")

    html = None
    status = 0
    try:
        html, status = _fetch_page(url, source, use_post=False)
        logs.append(f"Статус (GET): {status}")
    except Exception as e:
        logs.append(f"Ошибка GET: {e}")
        html = None

    if html:
        soup = BeautifulSoup(html, "html.parser")
        lessons = _parse_schedule_table(soup, source)
        if not lessons:
            logs.append("По GET расписание не найдено, пробуем POST…")
            try:
                html, status = _fetch_page(f"{BASE_URL}index.php", source, use_post=True)
                logs.append(f"Статус (POST): {status}")
                soup = BeautifulSoup(html, "html.parser")
                lessons = _parse_schedule_table(soup, source)
            except Exception as e:
                logs.append(f"Ошибка POST: {e}")
    else:
        lessons = []

    if save_debug_html and html:
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", source.query)[:50]
        with open(f"debug_{safe_name}.html", "w", encoding="utf-8") as f:
            f.write(html)
        logs.append("HTML сохранён в debug_*.html")

    logs.append(f"Найдено занятий: {len(lessons)}")
    return lessons, logs

def merge_sources(sources):
    result = {}
    conflicts = {}
    logs = []

    active = sorted(
        [s for s in sources if s.enabled],
        key=lambda s: s.priority,
        reverse=True
    )

    if not active:
        logs.append("⚠ Нет активных источников")

    for source in active:
        lessons, source_logs = fetch_schedule(source)
        logs.extend(source_logs)

        for lesson in lessons:
            key = (lesson.date, lesson.pair)
            if key not in result:
                result[key] = lesson
            else:
                if key not in conflicts:
                    conflicts[key] = [result[key]]
                conflicts[key].append(lesson)

    return list(result.values()), conflicts, logs

class LoadThread(QThread):
    finished_signal = Signal(list, dict, list)

    def __init__(self, sources):
        super().__init__()
        self.sources = sources

    def run(self):
        lessons, conflicts, logs = merge_sources(self.sources)
        self.finished_signal.emit(lessons, conflicts, logs)

class ConflictDialog(QDialog):
    def __init__(self, conflicts):
        super().__init__()
        self.setWindowTitle("Конфликты расписания")
        self.resize(500, 400)
        layout = QVBoxLayout()
        if not conflicts:
            layout.addWidget(QLabel("Конфликтов не найдено"))
        else:
            for key, lessons_list in conflicts.items():
                date, pair = key
                layout.addWidget(QLabel(f"<b>{date} | Пара {pair}</b>"))
                for lesson in lessons_list:
                    layout.addWidget(QLabel(f"  • {lesson.discipline} ({lesson.type}) — {lesson.owner}"))
                layout.addSpacing(10)
        self.setLayout(layout)

class AddSourceDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Добавить источник")
        self.resize(400, 260)
        layout = QFormLayout()

        self.type_box = QComboBox()
        self.type_box.addItems(["Группа", "Преподаватель"])
        self.type_box.currentTextChanged.connect(self._on_type_changed)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Отображаемое название")
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Например: БНИ-23-01 или Иванов И.И.")
        self.priority_input = QSpinBox()
        self.priority_input.setRange(1, 100)
        self.priority_input.setValue(10)
        self.priority_input.setToolTip("Больше — выше приоритет при конфликтах")

        layout.addRow("Тип поиска:", self.type_box)
        layout.addRow("Название:", self.name_input)
        self.query_label = QLabel("Группа:")
        layout.addRow(self.query_label, self.query_input)
        layout.addRow("Приоритет:", self.priority_input)

        btn = QPushButton("Добавить")
        btn.clicked.connect(self.accept)
        layout.addRow(btn)
        self.setLayout(layout)
        self._on_type_changed(self.type_box.currentText())

    def _on_type_changed(self, text):
        if "Преподаватель" in text:
            self.query_label.setText("ФИО преподавателя:")
        else:
            self.query_label.setText("Группа:")

    def get_source(self):
        st = "teacher" if "Преподаватель" in self.type_box.currentText() else "group"
        return Source(
            name=self.name_input.text().strip() or self.query_input.text().strip(),
            search_type=st,
            query=self.query_input.text().strip(),
            priority=self.priority_input.value(),
            enabled=True,
        )

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Расписание — raspisanie.rusoil.net")
        self.resize(1000, 700)

        self.sources = load_sources()
        if not self.sources:
            self.sources = [
                Source("БНИ-22-01", "group", "БНИ-22-01", 10, True),
                Source("ИУ-21-1", "group", "ИУ-21-1", 8, True),
            ]
            save_sources(self.sources)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.schedule_tab = QWidget()
        self.sources_tab = QWidget()
        self.tabs.addTab(self.schedule_tab, "Расписание")
        self.tabs.addTab(self.sources_tab, "Источники")

        self.init_schedule_tab()
        self.init_sources_tab()

    def init_schedule_tab(self):
        layout = QVBoxLayout(self.schedule_tab)

        self.schedule_stack = QStackedWidget()
        # Страница 0: расписание
        schedule_page = QWidget()
        schedule_layout = QVBoxLayout(schedule_page)
        self.load_btn = QPushButton("Поиск по списку источников")
        self.load_btn.clicked.connect(self.load_schedule)
        schedule_layout.addWidget(self.load_btn)
        schedule_layout.addWidget(QLabel("Дата и день недели | № пары | дисциплина (форма)"))
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        schedule_layout.addWidget(self.list_widget, stretch=1)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(120)
        schedule_layout.addWidget(QLabel("Статус:"))
        schedule_layout.addWidget(self.log_output)
        self.schedule_stack.addWidget(schedule_page)

        # Страница 1: конфликты (заменяет расписание по ТЗ [2.5])
        conflict_page = QWidget()
        conflict_layout = QVBoxLayout(conflict_page)
        self.conflict_back_btn = QPushButton("← Назад к расписанию")
        self.conflict_back_btn.clicked.connect(lambda: self.schedule_stack.setCurrentIndex(0))
        conflict_layout.addWidget(self.conflict_back_btn)
        self.conflict_scroll = QScrollArea()
        self.conflict_scroll.setWidgetResizable(True)
        self.conflict_scroll.setWidget(QFrame())
        self.conflict_scroll.widget().setLayout(QVBoxLayout())
        conflict_layout.addWidget(self.conflict_scroll)
        self.schedule_stack.addWidget(conflict_page)

        layout.addWidget(self.schedule_stack)

    def load_schedule(self):
        if not any(s.enabled for s in self.sources):
            QMessageBox.warning(self, "Ошибка", "Включите хотя бы один источник в списке источников.")
            return
        self.load_btn.setEnabled(False)
        self.load_btn.setText("Загрузка…")
        self.log_output.clear()
        self.thread = LoadThread(self.sources)
        self.thread.finished_signal.connect(self.display_schedule)
        self.thread.start()

    def display_schedule(self, lessons, conflicts, logs):
        self.list_widget.clear()
        if lessons:
            for lesson in sorted(lessons, key=lambda x: (x.date, x.pair)):
                self.list_widget.addItem(
                    f"{lesson.date} | Пара {lesson.pair} | {lesson.discipline} ({lesson.type}) — {lesson.owner}"
                )
        else:
            self.list_widget.addItem("Занятия не найдены. Проверьте запросы и подключение.")
        self.log_output.setPlainText("\n".join(logs))
        self.log_output.moveCursor(QTextCursor.Start)

        if conflicts:
            # По ТЗ [2.5]: окно конфликтов заменяет текущее функциональное окно
            container = self.conflict_scroll.widget()
            old_layout = container.layout()
            for i in reversed(range(old_layout.count())):
                w = old_layout.takeAt(i).widget()
                if w:
                    w.deleteLater()
            for key, lessons_list in conflicts.items():
                date, pair = key
                old_layout.addWidget(QLabel(f"<b>{date} | Пара {pair}</b>"))
                for lesson in lessons_list:
                    old_layout.addWidget(QLabel(f"  • {lesson.discipline} ({lesson.type}) — {lesson.owner}"))
                old_layout.addSpacing(12)
            self.schedule_stack.setCurrentIndex(1)
        else:
            self.schedule_stack.setCurrentIndex(0)

        self.load_btn.setEnabled(True)
        self.load_btn.setText("Поиск по списку источников")

    def init_sources_tab(self):
        layout = QVBoxLayout(self.sources_tab)
        sources_layout = QHBoxLayout()
        self.sources_list = QListWidget()
        self.sources_list.itemChanged.connect(self.on_source_changed)
        sources_layout.addWidget(self.sources_list, stretch=2)
        btn_layout = QVBoxLayout()
        add_btn = QPushButton("Добавить")
        add_btn.clicked.connect(self.add_source)
        del_btn = QPushButton("Удалить")
        del_btn.clicked.connect(self.delete_source)
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(lambda: save_sources(self.sources))
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(save_btn)
        btn_layout.addStretch()
        sources_layout.addLayout(btn_layout)
        layout.addLayout(sources_layout)
        self.refresh_sources()

    def refresh_sources(self):
        self.sources_list.blockSignals(True)
        self.sources_list.clear()
        # Отображение в порядке убывания приоритета (ТЗ [1.7])
        order = sorted(range(len(self.sources)), key=lambda i: (-self.sources[i].priority, i))
        for idx in order:
            s = self.sources[idx]
            item = QListWidgetItem(
                f"{s.name} | {'Группа' if s.search_type == 'group' else 'Преподаватель'} | приоритет {s.priority}"
            )
            item.setCheckState(Qt.Checked if s.enabled else Qt.Unchecked)
            item.setData(Qt.UserRole, idx)
            self.sources_list.addItem(item)
        self.sources_list.blockSignals(False)

    def on_source_changed(self, item):
        idx = item.data(Qt.UserRole)
        if isinstance(idx, int) and 0 <= idx < len(self.sources):
            self.sources[idx].enabled = item.checkState() == Qt.Checked
            save_sources(self.sources)

    def add_source(self):
        dlg = AddSourceDialog()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_source = dlg.get_source()
            if new_source.query:
                self.sources.append(new_source)
                save_sources(self.sources)
                self.refresh_sources()

    def delete_source(self):
        item = self.sources_list.currentItem()
        if item is None:
            return
        idx = item.data(Qt.UserRole)
        if not isinstance(idx, int) or idx < 0 or idx >= len(self.sources):
            return
        reply = QMessageBox.question(self, "Подтверждение", "Удалить этот источник?")
        if reply == QMessageBox.StandardButton.Yes:
            self.sources.pop(idx)
            save_sources(self.sources)
            self.refresh_sources()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
