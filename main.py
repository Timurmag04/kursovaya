import sys
import json
import re
import html
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional
import urllib.parse
import requests
from requests import Session
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

# Общая сессия для поддержания cookies/referer, как в браузере
SESSION = Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
})

WEEKDAY_ORDER = {
    "Пн": 1,
    "Пн.": 1,
    "Понедельник": 1,
    "Вт": 2,
    "Вт.": 2,
    "Вторник": 2,
    "Ср": 3,
    "Ср.": 3,
    "Среда": 3,
    "Чт": 4,
    "Чт.": 4,
    "Четверг": 4,
    "Пт": 5,
    "Пт.": 5,
    "Пятница": 5,
    "Сб": 6,
    "Сб.": 6,
    "Суббота": 6,
    "Вс": 7,
    "Вс.": 7,
    "Воскресенье": 7,
}

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
    filial: int = 1
    kaf: Optional[int] = None
    kaf_name: str = ""
    kid: Optional[int] = None
    vak: Optional[int] = None

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
    """
    Строит URL для получения расписания.
    - Для групп: index.php?gruppa=...
    - Для преподавателей:
        * если известны kid/vak и кафедра — как в showbegunokprep (Ajaxm.js)
        * иначе старый поиск по фамилии.
    """
    if source.search_type == "group":
        q = urllib.parse.quote_plus(source.query)
        return f"{BASE_URL}index.php?gruppa={q}&sem=0"

    # Преподаватель
    # Если в источнике сохранены реальные идентификаторы с сайта
    if source.kaf and (source.kid or source.vak):
        filial = source.filial or 1
        kaf = source.kaf
        family = urllib.parse.quote(source.query or "", encoding="utf-8")
        kafedra = urllib.parse.quote(source.kaf_name or "", encoding="utf-8")
        if source.kid:
            # Не вакансия
            return (
                f"{BASE_URL}index.php?"
                f"kid={source.kid}&vak=0&family={family}"
                f"&kaf={kaf}&kafedra={kafedra}&sem=0&filial={filial}"
            )
        # Вакансия
        return (
            f"{BASE_URL}index.php?"
            f"kid=0&vak={source.vak}&family={family}"
            f"&kaf={kaf}&kafedra={kafedra}&sem=0&filial={filial}"
        )

    # Fallback: поиск по фамилии, как раньше
    q = urllib.parse.quote_plus(source.query)
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


def _decode_ajax_html(raw: bytes) -> str:
    """Декодирует ответы Ajaxm.php (списки кафедр и преподавателей).

    Сайт иногда отвечает в utf-8, иногда в cp1251. Раньше мы ориентировались по
    фрагментам start008/start006, но в некоторых ответах их может не быть и мы
    получали кривой текст (особенно в случае докторских списков). Поэтому теперь
    смотрим просто на наличие кириллицы, а не только на служебные токены.
    """
    for enc in ("utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            # при удачном декоде либо есть кириллица, либо служебный маркер
            if re.search(r"[А-Яа-я]", text) or "start008" in text or "start006" in text:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    # ничего не подошло, просто прогоняем через utf-8 с заменой, чтобы не падать
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
            # Для преподавателя: если есть kid/vak, используем их вместе с другими параметрами
            if source.kid or source.vak:
                if source.kid:
                    data["kid"] = str(source.kid)
                    data["vak"] = "0"
                else:
                    data["kid"] = "0"
                    data["vak"] = str(source.vak)
                # Добавляем другие необходимые параметры для полного запроса
                data["family"] = source.query
                if source.kaf:
                    data["kaf"] = str(source.kaf)
                if source.kaf_name:
                    data["kafedra"] = source.kaf_name
                if source.filial:
                    data["filial"] = str(source.filial)
            else:
                # Fallback: по фамилии
                data["family"] = source.query
        r = requests.post(url, data=data, timeout=15, headers=headers)
    else:
        r = requests.get(url, timeout=15, headers=headers)
    html = _decode_schedule_html(r.content)
    return html, r.status_code



def _strip_week_range(text: str, current_week: int | None):
    """Уберём префикс с номером(ами) недели и проверим, нужно ли этот урок брать.

    Тексты на странице часто начинаются с диапазона недель, например:
    "31 - 31 Безопасность..." или "12".
    Если текущая неделя известна, возвращаем ``(True, cleaned_text)`` только
    когда она попадает в указанный промежуток. Иначе (нет префикса) — просто
    возвращаем исходный текст.
    """
    m = re.match(r"^(\d+)(?:\s*[-–]\s*(\d+))?\s+(.*)", text)
    if m:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if current_week is not None and not (start <= current_week <= end):
            return False, None
        return True, m.group(3)
    return True, text


def _parse_schedule_table(soup: BeautifulSoup, source: Source):
    """Парсит таблицу расписания: поддерживает оба формата.

    Формат 1 (для групп): День | Пара1-7 (по строкам)
    Формат 2 (для преподавателей): День | Пара1 | Пара2 | ... | Пара7 (по колонкам)
    """
    lessons = []

    # Попытаемся извлечь номер текущей учебной недели из текста страницы.
    current_week = None
    page_text = soup.get_text(" ", strip=True)
    mweek = re.search(r"идет\s+(\d+)\s+учебн", page_text, re.I)
    if mweek:
        try:
            current_week = int(mweek.group(1))
        except ValueError:
            current_week = None

    # Ищем таблицу, в которой есть заголовок «День недели»
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

        # Проверим формат: если в первой строке 8+ ячеек (День + 7 пар), это формат 2
        if len(first_row_cells) >= 8:
            lessons = _parse_horizontal_schedule(table, source, current_week)
        else:
            lessons = _parse_vertical_schedule(table, source, current_week)

        if lessons:
            break

    return lessons


def _parse_vertical_schedule(table, source: Source, current_week: int | None):
    """Парсит вертикальный формат: День | Пара | Содержание"""
    lessons = []
    rows = table.find_all("tr")
    current_day = ""

    for tr in rows[1:]:
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue

        if len(cells) == 3:
            # День явно указан в первой колонке
            current_day = cells[0].get_text(strip=True)
            pair_num = cells[1].get_text(strip=True)
            content_cell = cells[2]
        else:
            # День из предыдущей строки, пара в первой колонке
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

            ok, clean = _strip_week_range(line, current_week)
            if not ok:
                continue
            line = clean

            # Формат: ...Дисциплина(Л|П|лаб|сем) Преподаватель место
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

    return lessons


def _parse_horizontal_schedule(table, source: Source, current_week: int | None):
    """Парсит горизонтальный формат: День | Пара1 | Пара2 | ... | Пара7

    Поддерживает два варианта:
    1. Для групп: День | Пара1 | Пара2 | ... | Пара7 (по колонкам)
    2. Для преподавателей: День | 1 пара | 2 пара | ... (по колонкам с группами/кодами)
    """
    lessons = []
    rows = table.find_all("tr")
    if not rows:
        return lessons

    # Ищем строку с заголовками пар — может быть в позициях 0, 1 или 2
    # (иногда есть временная строка перед днями)
    header_row_idx = 0
    pair_numbers = []

    # Пытаемся найти заголовок с "День недели"
    for idx, row in enumerate(rows[:3]):
        row_text = row.get_text(strip=True)
        if "День недели" in row_text or "недели" in row_text:
            header_row_idx = idx
            break

    header_cells = rows[header_row_idx].find_all(["th", "td"])

    # Извлекаем номера пар из заголовков
    for i, cell in enumerate(header_cells):
        text = cell.get_text(strip=True)
        if i == 0:
            # Первая колонка — "День недели"
            continue
        # Пропускаем колонки с "ПЕРЕРЫВ" и другие не-пары
        if "ПЕРЕРЫВ" in text or "перерыв" in text:
            pair_numbers.append("")
            continue
        # Извлекаем номер пары (может быть "1", "1 пара", "Пара 1", "4 пара (веч.)" и т.д.)
        num_match = re.search(r"\d+", text)
        if num_match:
            pair_numbers.append(num_match.group())
        else:
            pair_numbers.append("")

    # Пропускаем заголовок и служебные строки (типа временной строки)
    # Начинаем со строки после заголовка
    for tr in rows[header_row_idx + 1:]:
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue

        # Первая ячейка должна содержать день недели или время
        day_cell = cells[0]
        day_text = day_cell.get_text(strip=True)

        # Проверяем, это ли день недели (исключаем временные строки вида "08:45-10:20")
        if re.match(r"^\d{2}:\d{2}", day_text):
            # Это временная строка, пропускаем
            continue

        weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс', 
                    'Пн.', 'Вт.', 'Ср.', 'Чт.', 'Пт.', 'Сб.', 'Вс.',
                    'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
        if not any(w in day_text for w in weekdays):
            continue

        # Обрабатываем каждую пару в этом дне
        for pair_idx, pair_cell in enumerate(cells[1:]):
            if pair_idx >= len(pair_numbers):
                break

            pair_num = pair_numbers[pair_idx]
            if not pair_num:
                continue

            raw = pair_cell.get_text(separator="\n")
            lines = [s.strip() for s in raw.split("\n") if s.strip() and s.strip() != "&nbsp;"]

            for line in lines:
                if len(line) < 3:
                    continue

                ok, clean = _strip_week_range(line, current_week)
                if not ok:
                    continue
                line = clean

                # Формат для групп: Дисциплина(Л|П|лаб|сем) Преподаватель место
                m = re.search(r"\((Л|П|лаб|сем)\)\s+(.+)$", line)
                if m:
                    lesson_type = m.group(1)
                    rest = line[: m.start()].strip()
                    discipline = re.sub(r"^\d+(?:\s*-\s*\d+)?(?:\s*\(\d+\))?\s+", "", rest).strip()
                    if not discipline:
                        discipline = rest
                else:
                    # Формат для преподавателей: Группы; Код; Аудитория(Тип)
                    # Пример: н31-31;34-34; БТБ-25-03*1;  а- 228(П);
                    m = re.search(r"(\d+[а-яА-Я]*)\s*\(([ЛПлсаб]+)\)\s*;", line)
                    if m:
                        # Это может быть комната с типом
                        lesson_type = m.group(2)
                        # Пытаемся найти дисциплину в коде (паттерн вроде БТБ-25-03)
                        code_match = re.search(r"[А-Яа-я]{2,4}-\d{2}-\d{2}", line)
                        if code_match:
                            discipline = code_match.group().strip()
                        else:
                            # Если нет кода, используем всю строку до комнаты
                            before_room = re.sub(r"\d+\([А-Яа-я]*\).*$", "", line).strip()
                            discipline = before_room if before_room else "Неизвестная дисциплина"
                    else:
                        # Не в ожидаемом формате
                        continue
                
                lessons.append(
                    Lesson(
                        date=day_text,
                        pair=pair_num,
                        discipline=discipline,
                        type=lesson_type,
                        owner=source.query,
                        priority=source.priority,
                    )
                )
    
    return lessons



def fetch_schedule(source: Source, save_debug_html: bool = True):
    logs = []
    
    # Для преподавателей на kid/vak используем GET (проще и надёжнее)
    if source.search_type == "teacher" and (source.kid or source.vak):
        logs.append(f"Преподаватель {source.query}: kid={source.kid}, vak={source.vak}")
        try:
            # Используем GET с правильно составленным URL
            url = build_url(source)
            logs.append(f"Запрос: {url[:100]}...")
            html, status = _fetch_page(url, source, use_post=False)
            logs.append(f"Статус (GET): {status}")
            
            # Проверяем, есть ли расписание в HTML (таблица с "День недели")
            if "День недели" in html:
                soup = BeautifulSoup(html, "html.parser")
                lessons = _parse_schedule_table(soup, source)
                if lessons:
                    logs.append(f"Расписание загружено успешно")
                else:
                    logs.append("Таблица найдена но занятия не распарсены")
            else:
                logs.append("Ответ не содержит расписание (нет 'День недели')")
                lessons = []
        except Exception as e:
            logs.append(f"Ошибка: {e}")
            lessons = []
            html = None
    else:
        # Для групп и преподавателей без kid/vak
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
            # Для преподавателей не нужно сводить по дате/паре —
            # иначе при одновременных занятиях разных преподавателей
            # останется только первый источник (видимое поведение).
            # Поэтому ключ для учителей включает владельца.
            if source.search_type == "teacher":
                key = (lesson.date, lesson.pair, lesson.owner)
            else:
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
                # поддерживаем разные форматы ключа
                date = key[0]
                pair = key[1] if len(key) > 1 else "?"
                owner_info = f" — {key[2]}" if len(key) > 2 else ""
                layout.addWidget(QLabel(f"<b>{date} | Пара {pair}{owner_info}</b>"))
                for lesson in lessons_list:
                    layout.addWidget(QLabel(f"  • {lesson.discipline} ({lesson.type}) — {lesson.owner}"))
                layout.addSpacing(10)
        self.setLayout(layout)

class AddSourceDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Добавить группу")
        self.resize(400, 200)
        layout = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Например: БНИ-23-01")
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Код группы с сайта, например БНИ-23-01")
        self.priority_input = QSpinBox()
        self.priority_input.setRange(1, 100)
        self.priority_input.setValue(10)
        self.priority_input.setToolTip("Больше — выше приоритет при конфликтах")

        layout.addRow("Название группы:", self.name_input)
        layout.addRow("Код группы:", self.query_input)
        layout.addRow("Приоритет:", self.priority_input)

        btn = QPushButton("Добавить")
        btn.clicked.connect(self.accept)
        layout.addRow(btn)
        self.setLayout(layout)
    def get_source(self):
        return Source(
            name=self.name_input.text().strip() or self.query_input.text().strip(),
            search_type="group",
            query=self.query_input.text().strip(),
            priority=self.priority_input.value(),
            enabled=True,
        )


class AddTeacherSourceDialog(QDialog):
    """Добавление преподавателя через реальные списки с сайта (как в браузере)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Добавить преподавателя")
        self.resize(500, 300)

        self._result_source: Optional[Source] = None

        layout = QFormLayout(self)

        # --- Филиал ---
        self.filial_box = QComboBox()
        self.filial_box.addItem("Уфа", 1)
        layout.addRow("Филиал:", self.filial_box)

        # --- Кафедры ---
        self.kaf_box = QComboBox()
        self.kaf_box.setEnabled(False)

        self.load_kaf_btn = QPushButton("Загрузить кафедры")
        self.load_kaf_btn.clicked.connect(self.load_kafedras)

        layout.addRow(self.load_kaf_btn)
        layout.addRow("Кафедра:", self.kaf_box)

        # --- Преподаватели ---
        self.teacher_box = QComboBox()
        self.teacher_box.setEnabled(False)

        self.load_teacher_btn = QPushButton("Загрузить преподавателей")
        self.load_teacher_btn.clicked.connect(self.load_teachers)

        layout.addRow(self.load_teacher_btn)
        layout.addRow("Преподаватель:", self.teacher_box)

        # --- Приоритет ---
        self.priority_input = QSpinBox()
        self.priority_input.setRange(1, 100)
        self.priority_input.setValue(10)
        layout.addRow("Приоритет:", self.priority_input)

        # --- Кнопка ---
        btn = QPushButton("Добавить")
        btn.clicked.connect(self.accept)
        layout.addRow(btn)

    # --------------------------------------------------

    def _post_ajax(self, payload: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{BASE_URL}index.php",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://raspisanie.rusoil.net",
            "Host": "raspisanie.rusoil.net",
        }

        # Попытка отправить как cp1251 (как в старых реалиях сайта), затем как utf-8.
        # Сервер иногда возвращает неконсистентный HTML, поэтому пытаемся несколько вариантов.
        last_exc = None
        last_text = None
        last_status = None
        last_headers = None
        last_raw = None

        # Попытка получить стартовые куки/стейт как делает браузер
        try:
            SESSION.get(f"{BASE_URL}index.php", timeout=8)
        except Exception:
            pass

        # Сначала попробуем отправить как строку (requests сам закодирует),
        # затем как cp1251 и utf-8 (байты) — иногда сервер ожидает конкретную кодировку.
        for enc in (None, "cp1251", "utf-8"):
            try:
                if enc is None:
                    data_to_send = payload
                    hdrs = headers.copy()
                    hdrs.pop("Content-Type", None)
                    hdrs["Content-Type"] = "application/x-www-form-urlencoded"
                else:
                    data_to_send = payload.encode(enc, errors="ignore")
                    hdrs = headers.copy()
                    hdrs["Content-Type"] = f"application/x-www-form-urlencoded; charset={ 'windows-1251' if enc=='cp1251' else 'utf-8' }"

                r = SESSION.post(
                    f"{BASE_URL}Ajaxm.php",
                    data=data_to_send,
                    headers=hdrs,
                    timeout=15,
                    allow_redirects=True,
                )
                last_raw = r.content
                last_status = getattr(r, "status_code", None)
                last_headers = dict(getattr(r, "headers", {}) or {})
                text = _decode_ajax_html(r.content)
                last_text = text
                # Если в ответе есть ожидаемые маркеры или селект — считаем успехом
                if ("start006" in text) or ("start008" in text) or ("<select" in text.lower()):
                    return text
            except Exception as e:
                last_exc = e

        # Если ответ пустой (например Content-Length: 0), попробуем сначала инициировать сессию ещё раз
        if last_raw is None or len(last_raw) == 0:
            try:
                SESSION.get(f"{BASE_URL}index.php", timeout=8)
                # Повторный POST (строка)
                r = SESSION.post(f"{BASE_URL}Ajaxm.php", data=payload, headers=headers, timeout=15)
                last_raw = r.content
                last_status = getattr(r, "status_code", None)
                last_headers = dict(getattr(r, "headers", {}) or {})
                last_text = _decode_ajax_html(r.content)
            except Exception:
                pass

        # Если ни один вариант не дал ожидаемых маркеров, но есть последний текст —
        # сохраним расширенную отладочную информацию и вернём текст для дальнейшей попытки парсинга.
        if last_text is not None:
            # Если в ответе нет привычных маркеров, сохраним файлы для диагностики.
            if not ("start006" in last_text or "start008" in last_text or "<select" in last_text.lower()):
                try:
                    with open("debug_ajax_response.html", "w", encoding="utf-8") as f:
                        f.write(last_text or "")
                    with open("debug_ajax_meta.txt", "w", encoding="utf-8") as f:
                        f.write(f"status: {last_status}\n")
                        f.write("headers:\n")
                        for k, v in (last_headers or {}).items():
                            f.write(f"{k}: {v}\n")
                        f.write(f"raw_bytes: {len(last_raw) if last_raw is not None else 'None'}\n")
                except Exception:
                    pass
            return last_text

        # Если ничего не получилось — попробуем финальный POST и пробросим исключение
        try:
            r = SESSION.post(f"{BASE_URL}Ajaxm.php", data=payload.encode("utf-8", errors="ignore"), headers=headers, timeout=15)
            return _decode_ajax_html(r.content)
        except Exception:
            if last_exc:
                raise last_exc
            raise

    # --------------------------------------------------

    def load_kafedras(self):
        """Получает список кафедр напрямую из HTML index.php и заполняет kaf_box."""
        self.kaf_box.clear()
        self.teacher_box.clear()
        self.teacher_box.setEnabled(False)

        filial = int(self.filial_box.currentData() or 1)

        # Пытаемся загрузить страницу, на которой уже содержится select с кафедрами.
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"{BASE_URL}index.php",
            }
            r = requests.get(f"{BASE_URL}index.php?filial={filial}", headers=headers, timeout=15)
            r.raise_for_status()
            page_html = _decode_ajax_html(r.content)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить страницу с кафедрами:\n{e}")
            return
        # 🔥 DEBUG: сохраняем HTML
        with open("debug_teachers.html", "w", encoding="utf-8") as f:
            f.write(page_html)
        raw = html.unescape(page_html)
        soup = BeautifulSoup(raw, "html.parser")
        # элемент, в который вставляется <select id="rfio" или блок slov_kafedr
        select = soup.find("select", id="rfio")
        if not select:
            select = soup.find("select", id=lambda v: v and "rfio" in v.lower())
        container = None
        if select and not select.find_all("option"):
            # возможно select самозакрывается; возьмём опции из родительского контейнера
            container = select.parent
        if not select:
            # окончательное усилие: просто любой <select> в контейнере slov_kafedr
            container = soup.find(id="slov_kafedr")
            if container:
                select = container.find("select")
        # если нашли контейнер, соберём options из него вместо select
        options = []
        if container:
            options = container.find_all("option")
        elif select:
            options = select.find_all("option")
        if not options:
            try:
                with open("debug_kafedr_response.html", "w", encoding="utf-8") as f:
                    f.write(raw)
            except Exception:
                pass
            QMessageBox.critical(self, "Ошибка", "Не удалось найти элемент с кафедрами на странице. Ответ записан в debug_kafedr_response.html")
            return

        for opt in options:
            value = opt.get("value")
            # use space separator so that newlines/<br> don't glue words together
            title = opt.get_text(separator=" ", strip=True)
            # текст может оказаться в неправильной кодировке (declare UTF-8, но на деле cp1251 bytes)
            try:
                # re-encode through latin1 to preserve raw bytes
                title = title.encode("latin1").decode("cp1251")
            except Exception:
                pass
            if not value or value == "0":
                continue
            try:
                kaf_id = int(value)
            except ValueError:
                continue
            self.kaf_box.addItem(title, kaf_id)

        if self.kaf_box.count() == 0:
            QMessageBox.warning(self, "Пусто", "Кафедры не найдены на странице.")
            return
        self.kaf_box.setEnabled(True)
    # --------------------------------------------------

    def load_teachers(self):
        """Получает список преподавателей для выбранной кафедры, используя index.php?kaf=..."""
        self.teacher_box.clear()

        if not self.kaf_box.currentData():
            QMessageBox.warning(self, "Ошибка", "Выберите кафедру.")
            return

        filial = int(self.filial_box.currentData() or 1)
        kaf_id = int(self.kaf_box.currentData())

        # Загрузим страницу для кафедры
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"{BASE_URL}index.php",
            }
            r = requests.get(f"{BASE_URL}index.php?kaf={kaf_id}&filial={filial}", headers=headers, timeout=15)
            r.raise_for_status()
            page_html = _decode_ajax_html(r.content)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить страницу преподавателей:\n{e}")
            return

        # 🔥 DEBUG: сохраняем HTML
        with open("debug_teachers.html", "w", encoding="utf-8") as f:
            f.write(page_html)

        raw = html.unescape(page_html)
        soup = BeautifulSoup(raw, "html.parser")
        select = soup.find("select", id="kadrvak")
        if not select:
            # иногда id может отсутствовать, ищем любой <select> с opt value содержащим '@'
            candidates = soup.find_all("select")
            for cand in candidates:
                opts = cand.find_all("option")
                for o in opts:
                    if "@" in (o.get("value") or ""):
                        select = cand
                        break
                if select:
                    break
        container = None
        options = []
        if select:
            options = select.find_all("option")
            if not options:
                container = select.parent
        if container:
            options = container.find_all("option")
        if not options:
            QMessageBox.critical(self, "Ошибка", "Не удалось найти список преподавателей на странице.")
            return

        # Обрабатываем каждую option — извлекаем по одному преподавателю.
        teachers_added = 0
        for opt in options:
            value = opt.get("value") or ""
            # берем только прямой текст внутри тега (если есть вложения, они
            # попадают в opt.contents и не учитываются) — это спасает при сломанной
            # разметке, когда один <option> содержит всех потомков.
            fio_parts = [t for t in opt.contents if isinstance(t, str)]
            fio = "".join(fio_parts).strip()
            fio = fio.replace("\xa0", " ").strip()

            # Если в одном option записано несколько фамилий, обрабатываем тоже.
            # Пример: "Асеев С.О. Астафьева А.Д.".
            if value != "0" and fio and len(fio) > 3:
                names = list(re.finditer(r'[А-Я][а-я]+ [А-Я]\.[А-Я]\.', fio))
                if len(names) > 1:
                    id_tokens = re.findall(r"\d+@\d+@", value)
                    if not id_tokens:
                        id_tokens = [value]
                    for idx, m in enumerate(names):
                        single_fio = m.group().strip()
                        if not single_fio:
                            continue
                        # декодируем на всякий случай cp1251
                        try:
                            single_fio = single_fio.encode("latin1").decode("cp1251")
                        except Exception:
                            pass
                        tok = id_tokens[idx] if idx < len(id_tokens) else id_tokens[0]
                        parts = tok.split("@")
                        if len(parts) >= 2:
                            try:
                                vak_flag = int(parts[0])
                                tid = int(parts[1])
                                self.teacher_box.addItem(single_fio, (vak_flag, tid))
                                teachers_added += 1
                            except ValueError:
                                pass
                    continue
            
            # Стандартная обработка одиночного ФИО
            # Декодируем кодировку если нужно
            try:
                fio = fio.encode("latin1").decode("cp1251")
            except Exception:
                pass
            
            # Пропускаем пустые и служебные опции
            if value == "0" or not fio or len(fio) < 2:
                continue
            
            # Парсим value в формате "flag@id"
            parts = value.split("@")
            if len(parts) < 2:
                continue
            
            try:
                vak_flag = int(parts[0])
                tid = int(parts[1])
            except ValueError:
                continue
            
            # Добавляем только этого преподавателя
            self.teacher_box.addItem(fio, (vak_flag, tid))
            teachers_added += 1

        if self.teacher_box.count() == 0:
            QMessageBox.critical(self, "Пусто", f"Преподаватели не найдены (обработано {teachers_added} опций). Смотрите debug_teachers.html.")
            return
        self.teacher_box.setEnabled(True)


    # --------------------------------------------------

    def accept(self):
        if not self.teacher_box.currentData():
            QMessageBox.warning(self, "Ошибка", "Выберите преподавателя.")
            return

        filial = int(self.filial_box.currentData() or 1)
        kaf_id = int(self.kaf_box.currentData())
        kaf_name = self.kaf_box.currentText()

        vak_flag, tid = self.teacher_box.currentData()
        fio = self.teacher_box.currentText()

        kid = tid if vak_flag == 0 else None
        vak = tid if vak_flag == 1 else None

        self._result_source = Source(
            name=f"{fio} ({kaf_name})",
            search_type="teacher",
            query=fio,
            priority=self.priority_input.value(),
            enabled=True,
            filial=filial,
            kaf=kaf_id,
            kaf_name=kaf_name,
            kid=kid,
            vak=vak,
        )

        super().accept()

    def get_source(self) -> Optional[Source]:
        return self._result_source

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
            def sort_key(lesson: Lesson):
                day = (lesson.date or "").strip()
                day_key = WEEKDAY_ORDER.get(day, 99)
                try:
                    pair_num = int(lesson.pair)
                except (TypeError, ValueError):
                    pair_num = 99
                return (day_key, pair_num, lesson.discipline)

            for lesson in sorted(lessons, key=sort_key):
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
                # ключ может быть (date, pair) или (date, pair, owner)
                date = key[0]
                pair = key[1] if len(key) > 1 else "?"
                owner_info = f" — {key[2]}" if len(key) > 2 else ""
                old_layout.addWidget(QLabel(f"<b>{date} | Пара {pair}{owner_info}</b>"))
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
        add_group_btn = QPushButton("Добавить группу")
        add_group_btn.clicked.connect(self.add_group_source)
        add_teacher_btn = QPushButton("Добавить преподавателя")
        add_teacher_btn.clicked.connect(self.add_teacher_source)
        del_btn = QPushButton("Удалить")
        del_btn.clicked.connect(self.delete_source)
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(lambda: save_sources(self.sources))

        btn_layout.addWidget(add_group_btn)
        btn_layout.addWidget(add_teacher_btn)
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

    def add_group_source(self):
        dlg = AddSourceDialog()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_source = dlg.get_source()
            if new_source and new_source.query:
                self.sources.append(new_source)
                save_sources(self.sources)
                self.refresh_sources()

    def add_teacher_source(self):
        dlg = AddTeacherSourceDialog()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_source = dlg.get_source()
            if new_source is not None:
                self.sources.append(new_source)
                save_sources(self.sources)
                self.refresh_sources()

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