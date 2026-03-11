import sys
import json
import re
import html
from dataclasses import dataclass, asdict, field
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
    QDialog, QFormLayout, QStackedWidget,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal

SOURCES_FILE = "sources.json"
BASE_URL = "https://raspisanie.rusoil.net/rasp_old/"

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
    groups: List[str] = field(default_factory=list)
    auditorium: str = "онлайн"


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
    if source.search_type == "group":
        q = urllib.parse.quote_plus(source.query)
        return f"{BASE_URL}index.php?gruppa={q}&sem=0"

    if source.kaf and (source.kid or source.vak):
        filial = source.filial or 1
        kaf = source.kaf
        family = urllib.parse.quote(source.query or "", encoding="utf-8")
        kafedra = urllib.parse.quote(source.kaf_name or "", encoding="utf-8")
        if source.kid:
            return (
                f"{BASE_URL}index.php?"
                f"kid={source.kid}&vak=0&family={family}"
                f"&kaf={kaf}&kafedra={kafedra}&sem=0&filial={filial}"
            )
        return (
            f"{BASE_URL}index.php?"
            f"kid=0&vak={source.vak}&family={family}"
            f"&kaf={kaf}&kafedra={kafedra}&sem=0&filial={filial}"
        )

    q = urllib.parse.quote_plus(source.query)
    return f"{BASE_URL}index.php?family={q}&sem=0"


def _decode_schedule_html(raw: bytes) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            if "День недели" in text or "расписан" in text.lower():
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _decode_ajax_html(raw: bytes) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            if re.search(r"[А-Яа-я]", text) or "start008" in text or "start006" in text:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _fetch_page(url: str, source: Source, use_post: bool) -> Tuple[str, int]:
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
            if source.kid or source.vak:
                if source.kid:
                    data["kid"] = str(source.kid)
                    data["vak"] = "0"
                else:
                    data["kid"] = "0"
                    data["vak"] = str(source.vak)
                data["family"] = source.query
                if source.kaf:
                    data["kaf"] = str(source.kaf)
                if source.kaf_name:
                    data["kafedra"] = source.kaf_name
                if source.filial:
                    data["filial"] = str(source.filial)
            else:
                data["family"] = source.query
        r = requests.post(url, data=data, timeout=15, headers=headers)
    else:
        r = requests.get(url, timeout=15, headers=headers)
    html_text = _decode_schedule_html(r.content)
    return html_text, r.status_code


def _strip_week_range(text: str, current_week: int | None):
    m = re.match(r"^(\d+)(?:\s*[-–]\s*(\d+))?\s+(.*)", text)
    if m:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if current_week is not None and not (start <= current_week <= end):
            return False, None
        return True, m.group(3)
    return True, text


def _parse_schedule_table(soup: BeautifulSoup, source: Source):
    lessons = []

    current_week = None
    page_text = soup.get_text(" ", strip=True)
    mweek = re.search(r"идет\s+(\d+)\s+учебн", page_text, re.I)
    if mweek:
        try:
            current_week = int(mweek.group(1))
        except ValueError:
            current_week = None

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

        if len(first_row_cells) >= 8:
            lessons = _parse_horizontal_schedule(table, source, current_week)
        else:
            lessons = _parse_vertical_schedule(table, source, current_week)

        if lessons:
            break

    return lessons


def _parse_vertical_schedule(table, source: Source, current_week: int | None):
    lessons = []
    rows = table.find_all("tr")
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

            if source.search_type == "teacher":
                parsed = _parse_teacher_line(line, current_week, current_day, pair_num, source)
                if parsed:
                    lessons.append(parsed)
            else:
                ok, clean = _strip_week_range(line, current_week)
                if not ok:
                    continue
                line = clean

                m = re.search(r"\((Л|П|лаб|сем)\)\s+(.+)$", line)
                if not m:
                    continue
                lesson_type = m.group(1)
                rest = line[: m.start()].strip()
                discipline = re.sub(r"^\d+(?:\s*-\s*\d+)?(?:\s*\(\d+\))?\s+", "", rest).strip()
                if not discipline:
                    discipline = rest

                after_type = m.group(2).strip()
                parts = after_type.split()
                auditorium = "онлайн"
                if parts and re.match(r"[а-яА-Я]?-?\d+[ -]?\d*", parts[-1]):
                    auditorium = parts[-1]

                lessons.append(
                    Lesson(
                        date=current_day,
                        pair=pair_num,
                        discipline=discipline,
                        type=lesson_type,
                        owner=source.query,
                        priority=source.priority,
                        auditorium=auditorium,
                    )
                )

    return lessons


def _parse_horizontal_schedule(table, source: Source, current_week: int | None):
    lessons = []
    rows = table.find_all("tr")
    if not rows:
        return lessons

    header_row_idx = -1
    pair_numbers = []
    break_col_indices = set()

    for idx, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        if len(cells) < 10:
            continue
        if "День недели" in cells[0].get_text(strip=True):
            header_row_idx = idx
            for col_idx, cell in enumerate(cells[1:], 1):
                text = cell.get_text(strip=True).upper()
                if "ПЕРЕРЫВ" in text or "ПЕРЕ" in text:
                    pair_numbers.append("")
                    break_col_indices.add(col_idx)
                else:
                    m = re.search(r"\d+", text)
                    pair_numbers.append(m.group() if m else "")
            break

    if header_row_idx == -1:
        return lessons

    for tr in rows[header_row_idx + 1:]:
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue

        day_text = cells[0].get_text(strip=True).strip()
        if re.match(r"^\d{2}:\d{2}", day_text) or len(day_text) < 3:
            continue
        if not any(w in day_text for w in WEEKDAY_ORDER.keys()):
            continue

        for cell_idx, pair_cell in enumerate(cells[1:], 1):
            if cell_idx in break_col_indices:
                continue

            if cell_idx - 1 >= len(pair_numbers):
                break

            pair_num = pair_numbers[cell_idx - 1]
            if not pair_num or not pair_num.isdigit():
                continue

            raw_html = str(pair_cell)
            parts = re.split(r"<br\s*/?>", raw_html)
            for part in parts:
                line = BeautifulSoup(part, "html.parser").get_text(" ", strip=True)
                line = re.sub(r"\s+", " ", line).strip()
                if len(line) < 8 or "nbsp" in line.lower():
                    continue

                parsed = _parse_teacher_line(line, current_week, day_text, pair_num, source)
                if parsed:
                    lessons.append(parsed)

    return lessons


def _parse_teacher_line(line: str, current_week: Optional[int], day: str, pair: str, source: Source) -> Optional[Lesson]:
    line = line.strip()
    if not line:
        return None

    line = re.sub(r"\s+", " ", line)

    tokens = [t.strip() for t in re.split(r"[;\s]+", line) if t.strip()]

    week_ranges = []
    groups = []
    lesson_type = ""
    auditorium = "онлайн"
    disc_code = ""

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        if re.match(r"^н?\d+-\d+$", tok):
            m = re.match(r"^н?(\d+)-(\d+)$", tok)
            if m:
                week_ranges.append((int(m.group(1)), int(m.group(2))))
            i += 1
            continue

        if re.search(r"[А-Яа-я]{2,5}-\d{2}-\d{2}(?:-\d)?\*\d+", tok):
            groups.append(tok)
            i += 1
            continue

        m = re.match(r"^([аa][ -]?(?:on[- ]line|\d+(?:-\d+)?))\s*(\d*)\s*\(([ЛПлабсем]+)\)$", tok, re.I)
        if m:
            aud = m.group(1).strip()
            code = m.group(2).strip()
            lt = m.group(3).upper()
            lesson_type = lt
            if "on" in aud.lower() or "line" in aud.lower():
                auditorium = "онлайн"
            else:
                auditorium = aud
            if code:
                disc_code = code
            i += 1
            continue

        m = re.match(r"^(\d+)\s*\(([ЛПлабсем]+)\)$", tok)
        if m:
            if not disc_code:
                disc_code = m.group(1)
            lesson_type = m.group(2).upper()
            i += 1
            continue

        i += 1

    if week_ranges and current_week is not None:
        if not any(s <= current_week <= e for s, e in week_ranges):
            return None

    if not lesson_type:
        return None

    discipline = "Занятие"
    if groups:
        groups_str = ", ".join(sorted(set(groups)))
        discipline = f"Занятие с группами {groups_str}"
        if disc_code:
            discipline += f" ({disc_code})"

    return Lesson(
        date=day,
        pair=pair,
        discipline=discipline,
        type=lesson_type,
        owner=source.query,
        priority=source.priority,
        groups=groups,
        auditorium=auditorium,
    )


def fetch_schedule(source: Source):
    if source.search_type == "teacher" and (source.kid or source.vak):
        try:
            url = build_url(source)
            html_text, status = _fetch_page(url, source, use_post=False)
            if "День недели" in html_text:
                soup = BeautifulSoup(html_text, "html.parser")
                lessons = _parse_schedule_table(soup, source)
            else:
                lessons = []
        except Exception:
            lessons = []
            html_text = None
    else:
        url = build_url(source)

        html_text = None
        try:
            html_text, status = _fetch_page(url, source, use_post=False)
        except Exception:
            html_text = None

        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")
            lessons = _parse_schedule_table(soup, source)
            if not lessons:
                try:
                    html_text, status = _fetch_page(f"{BASE_URL}index.php", source, use_post=True)
                    soup = BeautifulSoup(html_text, "html.parser")
                    lessons = _parse_schedule_table(soup, source)
                except Exception:
                    lessons = []
        else:
            lessons = []

    lessons = compact_consecutive_pairs(lessons)
    return lessons


def compact_consecutive_pairs(lessons: List[Lesson]) -> List[Lesson]:
    if not lessons:
        return lessons

    lessons.sort(
        key=lambda l: (
            WEEKDAY_ORDER.get(l.date.strip(), 99),
            int(l.pair.split("-")[0] if "-" in l.pair else l.pair or 999),
        )
    )

    compacted = []
    current = None

    for lesson in lessons:
        if current is not None:
            same_day = current.date.strip() == lesson.date.strip()
            same_disc = current.discipline == lesson.discipline
            same_type = current.type == lesson.type
            same_owner = current.owner == lesson.owner
            same_groups = current.groups == lesson.groups
            same_aud = current.auditorium == lesson.auditorium

            prev_last = int(current.pair.split("-")[-1]) if "-" in current.pair else int(current.pair)
            next_first = int(lesson.pair.split("-")[0]) if "-" in lesson.pair else int(lesson.pair)

            consecutive = next_first == prev_last + 1

            if same_day and same_disc and same_type and same_owner and same_groups and same_aud and consecutive:
                if "-" in current.pair:
                    start, _ = current.pair.split("-")
                    current.pair = f"{start}-{lesson.pair}"
                else:
                    current.pair = f"{current.pair}-{lesson.pair}"
                continue
        if current is not None:
            compacted.append(current)

        current = lesson

    if current is not None:
        compacted.append(current)

    return compacted


def merge_sources(sources):
    result: Dict[Tuple, Lesson] = {}
    conflicts: Dict[Tuple, List[Lesson]] = {}

    active = [s for s in sources if s.enabled]

    if not active:
        return [], {}

    active_sorted = sorted(
        active,
        key=lambda s: (
            -s.priority,
            0 if s.search_type == "teacher" else 1,
            s.name.lower(),
        ),
    )

    for source in active_sorted:
        lessons = fetch_schedule(source)

        for lesson in lessons:
            key = (lesson.date, lesson.pair, lesson.owner) if source.search_type == "teacher" else (lesson.date, lesson.pair)

            if key not in result:
                result[key] = lesson
            else:
                if key not in conflicts:
                    conflicts[key] = [result[key]]
                conflicts[key].append(lesson)

    final_lessons = list(result.values())

    final_lessons.sort(
        key=lambda l: (
            WEEKDAY_ORDER.get(l.date.strip(), 99),
            int(l.pair.split("-")[0]) if "-" in l.pair else int(l.pair or 99),
        )
    )

    return final_lessons, conflicts


class LoadThread(QThread):
    finished_signal = Signal(list, dict)

    def __init__(self, sources):
        super().__init__()
        self.sources = sources

    def run(self):
        lessons, conflicts = merge_sources(self.sources)
        self.finished_signal.emit(lessons, conflicts)


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
                date = key[0]
                pair = key[1] if len(key) > 1 else "?"
                owner_info = f" — {key[2]}" if len(key) > 2 else ""
                layout.addWidget(QLabel(f"<b>{date} | Пара {pair}{owner_info}</b>"))
                for lesson in lessons_list:
                    groups_str = ", ".join(lesson.groups) if lesson.groups else ""
                    aud_str = lesson.auditorium
                    layout.addWidget(
                        QLabel(
                            f"  • {lesson.discipline} ({lesson.type}) — {lesson.owner} {groups_str} {aud_str}"
                        )
                    )
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Добавить преподавателя")
        self.resize(500, 300)

        self._result_source: Optional[Source] = None

        layout = QFormLayout(self)

        self.filial_box = QComboBox()
        self.filial_box.addItem("Уфа", 1)
        layout.addRow("Филиал:", self.filial_box)

        self.kaf_box = QComboBox()
        self.kaf_box.setEnabled(False)

        self.load_kaf_btn = QPushButton("Загрузить кафедры")
        self.load_kaf_btn.clicked.connect(self.load_kafedras)

        layout.addRow(self.load_kaf_btn)
        layout.addRow("Кафедра:", self.kaf_box)

        self.teacher_box = QComboBox()
        self.teacher_box.setEnabled(False)

        self.load_teacher_btn = QPushButton("Загрузить преподавателей")
        self.load_teacher_btn.clicked.connect(self.load_teachers)

        layout.addRow(self.load_teacher_btn)
        layout.addRow("Преподаватель:", self.teacher_box)

        self.priority_input = QSpinBox()
        self.priority_input.setRange(1, 100)
        self.priority_input.setValue(10)
        layout.addRow("Приоритет:", self.priority_input)

        btn = QPushButton("Добавить")
        btn.clicked.connect(self.accept)
        layout.addRow(btn)

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

        try:
            SESSION.get(f"{BASE_URL}index.php", timeout=8)
        except Exception:
            pass

        last_raw = None
        last_status = None
        last_headers = None
        last_text = None
        last_exc = None

        for enc in (None, "cp1251", "utf-8"):
            try:
                if enc is None:
                    data_to_send = payload
                    hdrs = headers.copy()
                    hdrs["Content-Type"] = "application/x-www-form-urlencoded"
                else:
                    data_to_send = payload.encode(enc, errors="ignore")
                    hdrs = headers.copy()
                    hdrs["Content-Type"] = (
                        "application/x-www-form-urlencoded; charset=windows-1251"
                        if enc == "cp1251"
                        else "application/x-www-form-urlencoded; charset=utf-8"
                    )

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
                if ("start006" in text) or ("start008" in text) or ("<select" in text.lower()):
                    return text
                last_text = text
            except Exception as e:
                last_exc = e

        if last_raw is None or len(last_raw) == 0:
            try:
                SESSION.get(f"{BASE_URL}index.php", timeout=8)
                r = SESSION.post(
                    f"{BASE_URL}Ajaxm.php", data=payload, headers=headers, timeout=15
                )
                last_raw = r.content
                last_status = getattr(r, "status_code", None)
                last_headers = dict(getattr(r, "headers", {}) or {})
                last_text = _decode_ajax_html(r.content)
            except Exception:
                pass

        if last_text is not None:
            return last_text

        try:
            r = SESSION.post(
                f"{BASE_URL}Ajaxm.php",
                data=payload.encode("utf-8", errors="ignore"),
                headers=headers,
                timeout=15,
            )
            return _decode_ajax_html(r.content)
        except Exception:
            if last_exc:
                raise last_exc
            raise

    def load_kafedras(self):
        self.kaf_box.clear()
        self.teacher_box.clear()
        self.teacher_box.setEnabled(False)

        filial = int(self.filial_box.currentData() or 1)

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

        raw = html.unescape(page_html)
        soup = BeautifulSoup(raw, "html.parser")
        select = soup.find("select", id="rfio")
        if not select:
            select = soup.find("select", id=lambda v: v and "rfio" in v.lower())
        container = None
        if select and not select.find_all("option"):
            container = select.parent
        if not select:
            container = soup.find(id="slov_kafedr")
            if container:
                select = container.find("select")
        options = []
        if container:
            options = container.find_all("option")
        elif select:
            options = select.find_all("option")
        if not options:
            QMessageBox.critical(
                self,
                "Ошибка",
                "Не удалось найти элемент с кафедрами на странице.",
            )
            return
        for opt in options:
            value = opt.get("value")
            title = opt.get_text(separator=" ", strip=True)
            try:
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

    def load_teachers(self):
        self.teacher_box.clear()

        if not self.kaf_box.currentData():
            QMessageBox.warning(self, "Ошибка", "Выберите кафедру.")
            return

        filial = int(self.filial_box.currentData() or 1)
        kaf_id = int(self.kaf_box.currentData())

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"{BASE_URL}index.php",
            }
            r = requests.get(
                f"{BASE_URL}index.php?kaf={kaf_id}&filial={filial}", headers=headers, timeout=15
            )
            r.raise_for_status()
            page_html = _decode_ajax_html(r.content)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить страницу преподавателей:\n{e}")
            return

        raw = html.unescape(page_html)
        soup = BeautifulSoup(raw, "html.parser")
        select = soup.find("select", id="kadrvak")
        if not select:
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

        teachers_added = 0
        for opt in options:
            value = opt.get("value") or ""
            fio_parts = [t for t in opt.contents if isinstance(t, str)]
            fio = "".join(fio_parts).strip()
            fio = fio.replace("\xa0", " ").strip()

            if value != "0" and fio and len(fio) > 3:
                names = list(re.finditer(r"[А-Я][а-я]+ [А-Я]\.[А-Я]\.", fio))
                if len(names) > 1:
                    id_tokens = re.findall(r"\d+@\d+@", value)
                    if not id_tokens:
                        id_tokens = [value]
                    for idx, m in enumerate(names):
                        single_fio = m.group().strip()
                        if not single_fio:
                            continue
                        try:
                            single_fio = single_fio.encode("latin1").decode("cp1251")
                        except Exception:
                            pass
                        tok = id_tokens[idx] if idx < len(id_tokens) else id_tokens[0]
                        parts_val = tok.split("@")
                        if len(parts_val) >= 2:
                            try:
                                vak_flag = int(parts_val[0])
                                tid = int(parts_val[1])
                                self.teacher_box.addItem(single_fio, (vak_flag, tid))
                                teachers_added += 1
                            except ValueError:
                                pass
                    continue

            try:
                fio = fio.encode("latin1").decode("cp1251")
            except Exception:
                pass

            if value == "0" or not fio or len(fio) < 2:
                continue

            parts_val = value.split("@")
            if len(parts_val) < 2:
                continue

            try:
                vak_flag = int(parts_val[0])
                tid = int(parts_val[1])
            except ValueError:
                continue

            self.teacher_box.addItem(fio, (vak_flag, tid))
            teachers_added += 1

        if self.teacher_box.count() == 0:
            QMessageBox.critical(
                self,
                "Пусто",
                f"Преподаватели не найдены (обработано {teachers_added} опций).",
            )
            return
        self.teacher_box.setEnabled(True)

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
        schedule_page = QWidget()
        schedule_layout = QVBoxLayout(schedule_page)
        self.load_btn = QPushButton("Поиск по списку источников")
        self.load_btn.clicked.connect(self.load_schedule)
        schedule_layout.addWidget(self.load_btn)
        schedule_layout.addWidget(QLabel("Дата и день недели | № пары | дисциплина (форма)"))
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        schedule_layout.addWidget(self.list_widget, stretch=1)
        self.schedule_stack.addWidget(schedule_page)

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
        self.thread = LoadThread(self.sources)
        self.thread.finished_signal.connect(self.display_schedule)
        self.thread.start()

    def display_schedule(self, lessons, conflicts):
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
                groups_str = ", ".join(lesson.groups) if lesson.groups else ""
                aud_str = lesson.auditorium
                dis_str = f"{lesson.discipline} " if lesson.discipline else ""
                self.list_widget.addItem(
                    f"{lesson.date} | Пара {lesson.pair} | {dis_str}({lesson.type}) {groups_str} {aud_str} — {lesson.owner}"
                )
        else:
            self.list_widget.addItem("Занятия не найдены. Проверьте запросы и подключение.")

        if conflicts:
            container = self.conflict_scroll.widget()
            old_layout = container.layout()
            for i in reversed(range(old_layout.count())):
                w = old_layout.takeAt(i).widget()
                if w:
                    w.deleteLater()
            for key, lessons_list in conflicts.items():
                date = key[0]
                pair = key[1] if len(key) > 1 else "?"
                owner_info = f" — {key[2]}" if len(key) > 2 else ""
                old_layout.addWidget(QLabel(f"<b>{date} | Пара {pair}{owner_info}</b>"))
                for lesson in lessons_list:
                    groups_str = ", ".join(lesson.groups) if lesson.groups else ""
                    aud_str = lesson.auditorium
                    old_layout.addWidget(
                        QLabel(
                            f"  • {lesson.discipline} ({lesson.type}) — {lesson.owner} {groups_str} {aud_str}"
                        )
                    )
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
