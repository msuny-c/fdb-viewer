#!/usr/bin/env python3
"""
Фоновая утилита: ищет ответы в .fdb и кладет их в буфер обмена по Cmd+Shift+Z.
"""
import difflib
import html
import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import pyperclip
from pynput import keyboard

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.parser import decode_tags, process_questions  # noqa: E402

FDB_DIR = Path(os.getenv("FDB_DIR", ROOT / "fdb"))
MIN_SCORE = 0.55  # минимальная похожесть, чтобы принять совпадение

PUNCT_RE = re.compile(r"[.,!?;:\"'`“”«»„…()\\[\\]{}<>/\\\\|@#$%^&*_+=-]+")


@dataclass
class QuestionEntry:
    qid: str
    question: str
    answers: List[str]
    q_type: int
    right: int
    source: str
    norm: str
    norm_nospace: str


def strip_html_to_text(value: str) -> str:
    """Очищает HTML/BR, переводит небуквенные пробелы и упрощает переносы строк."""
    if not value:
        return ""
    text = html.unescape(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def normalize(text: str, drop_spaces: bool = False) -> str:
    plain = strip_html_to_text(text)
    plain = plain.lower().replace("ё", "е")
    plain = PUNCT_RE.sub(" ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if drop_spaces:
        plain = plain.replace(" ", "")
    return plain


def load_fdb_file(path: Path) -> List[QuestionEntry]:
    with path.open("rb") as f:
        raw = f.read()
    try:
        content = raw.decode("cp1251", errors="ignore")
    except Exception:
        content = raw.decode("utf-8", errors="ignore")

    decoded_tags, _ = decode_tags(content)
    xml_data = "\n".join(decoded_tags)
    questions = process_questions(xml_data)

    entries: List[QuestionEntry] = []
    for qid, qdata in questions.items():
        question_text = strip_html_to_text(qdata.get("question", ""))
        if not question_text:
            continue
        answers_raw = qdata.get("answers") or []
        answers_text: List[str] = []
        for a in answers_raw:
            cleaned = strip_html_to_text(a)
            if cleaned:
                answers_text.append(cleaned)

        q_type = int(qdata.get("type") or 1)
        right = int(qdata.get("right") or 1)
        norm = normalize(question_text)
        entries.append(
            QuestionEntry(
                qid=qid,
                question=question_text,
                answers=answers_text,
                q_type=q_type,
                right=right,
                source=path.name,
                norm=norm,
                norm_nospace=normalize(question_text, drop_spaces=True),
            )
        )
    return entries


def load_all_questions(folder: Path) -> List[QuestionEntry]:
    folder.mkdir(parents=True, exist_ok=True)
    fdb_files = sorted(folder.glob("*.fdb"))
    entries: List[QuestionEntry] = []
    for file in fdb_files:
        try:
            entries.extend(load_fdb_file(file))
        except Exception as exc:
            print(f"[warn] Не удалось разобрать {file.name}: {exc}")
    print(
        f"[init] Загружено {len(entries)} вопросов из {len(fdb_files)} .fdb "
        f"в каталоге {folder}"
    )
    if not fdb_files:
        print("[hint] Положите .fdb в папку fdp и перезапустите утилиту.")
    return entries


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def format_answer(entry: QuestionEntry) -> str:
    """
    Возвращает строку для буфера обмена:
    - Если вариантов несколько, кладём сами ответы (каждый с номерацией 1-based, через перенос строки).
    - Для одиночного выбора (тип 1) — первый вариант.
    - Для свободного ввода (тип 7) — первый текстовый вариант.
    - Фолбэк: если нет ответов — пусто; если есть несколько — все с номерами; иначе первый.
    """
    answers = entry.answers
    if not answers:
        return ""

    t = entry.q_type
    right = max(1, entry.right or 1)

    if t == 1:
        return (answers[0] or "").strip()
    if t == 2:
        picked = answers[: min(len(answers), right)]
        return "\n".join(f"{i}) {(ans or '').replace(chr(10), ' ').strip()}" for i, ans in enumerate(picked, 1))
    if t in (3, 6):  # порядок/соответствия — отдаём весь порядок
        return "\n".join(f"{i}) {(ans or '').replace(chr(10), ' ').strip()}" for i, ans in enumerate(answers, 1))
    if t == 7:
        return (answers[0] or "").strip()

    # Фолбэк
    if len(answers) > 1:
        picked = answers[: min(len(answers), right)]
        return "\n".join(f"{i}) {(ans or '').replace(chr(10), ' ').strip()}" for i, ans in enumerate(picked, 1))
    return (answers[0] or "").strip()


def best_match(query: str, data: List[QuestionEntry]) -> Optional[Tuple[QuestionEntry, float]]:
    norm_q = normalize(query)
    norm_q_ns = normalize(query, drop_spaces=True)
    if not norm_q:
        return None

    best: Optional[Tuple[QuestionEntry, float]] = None
    for entry in data:
        s1 = similarity(norm_q, entry.norm)
        s2 = similarity(norm_q_ns, entry.norm_nospace)
        bonus = 0.1 if norm_q in entry.norm else 0.0
        score = max(s1, s2) + bonus
        if best is None or score > best[1]:
            best = (entry, score)
    if best and best[1] >= MIN_SCORE:
        return best
    return None


class HotkeyService:
    def __init__(self, data: List[QuestionEntry]):
        self.data = data
        self._lock = threading.Lock()

    def handle_trigger(self):
        with self._lock:
            clipboard_text = pyperclip.paste() or ""
            match = best_match(clipboard_text, self.data)
            if not match:
                print("[miss] Совпадений не найдено, буфер не трогаю.")
                return

            entry, score = match
            answer_text = format_answer(entry)
            if not answer_text:
                print(f"[warn] У вопроса {entry.qid} нет вариантов ответа.")
                return

            pyperclip.copy(answer_text)
            print(
                f"[ok] {entry.source} #{entry.qid} "
                f"(score={score:.2f}) → ответ помещён в буфер."
            )

    def start(self):
        print("Готово: скопируйте текст вопроса и нажмите Cmd+Shift+Z.")
        with keyboard.GlobalHotKeys({"<cmd>+<shift>+z": self.handle_trigger}) as h:
            h.join()


def main():
    data = load_all_questions(FDB_DIR)
    service = HotkeyService(data)
    try:
        service.start()
    except KeyboardInterrupt:
        print("\n[exit] Остановлено пользователем.")


if __name__ == "__main__":
    main()
