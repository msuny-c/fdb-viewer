# -*- coding: utf-8 -*-
from functools import reduce
import re, binascii, codecs
from typing import Dict, List, Tuple

def _strip_many(text: str, repls: List[str]) -> str:
    return reduce(lambda a, v: a.replace(v, ''), repls, text)

def decode_tags(data: str) -> Tuple[List[str], str]:
    """
    Декодирует <id>HEX</id> и <gr-id>HEX</gr-id> (cp1251).
    Возвращает: (decoded_tags_xml_snippets, gr_data_text)
    """
    repls = [',', '\\', '\n', ' ', '\r\n', '\r']
    pattern = r'<(\d+)>(.*?)<\/\1>'
    tags = re.findall(pattern, data, re.DOTALL)
    decoded_tags = []

    for tag_id, hex_data in tags:
        hex_clean = _strip_many(hex_data, repls)
        if not hex_clean:
            continue
        try:
            decoded_bytes = binascii.unhexlify(hex_clean)
            decoded_text = codecs.decode(decoded_bytes, 'cp1251', errors='ignore')
        except Exception:
            decoded_text = ''
        decoded_tags.append(f'<{tag_id}>\n{decoded_text}</{tag_id}>')

    gr_text = ''
    gr_pattern = r'<gr-id>(.*?)</gr-id>'
    gr_matches = re.findall(gr_pattern, data, re.DOTALL)
    if gr_matches:
        hex_clean = _strip_many(gr_matches[0], repls)
        try:
            gr_bytes = binascii.unhexlify(hex_clean)
            gr_text = codecs.decode(gr_bytes, 'cp1251', errors='ignore')
        except Exception:
            gr_text = ''
    return decoded_tags, gr_text

def process_questions(xml_data: str) -> Dict[str, dict]:
    """
    Парсит <N>...</N> → dict[id]={ id, question, type, right, answers }
    """
    strip_in_q = ['\n', '\r\n', '\r']
    question_blocks = re.findall(r'<\d+>.*?</\d+>', xml_data, re.DOTALL)
    out: Dict[str, dict] = {}

    for block in question_blocks:
        id_match = re.search(r'<(\d+)>', block)
        qid = id_match.group(1) if id_match else None
        if not qid:
            continue

        q_match = re.search(r'<question>(.*?)</question>', block, re.DOTALL | re.IGNORECASE)
        question_raw = (q_match.group(1).strip() if q_match else '').strip()
        question_clean = _strip_many(question_raw, strip_in_q)

        t_match = re.search(r'type\s*=\s*(\d+)', block)
        r_match = re.search(r'right\s*=\s*(\d+)', block)
        q_type = int(t_match.group(1)) if t_match else 1
        q_right = int(r_match.group(1)) if r_match else 1

        answers = re.findall(r'<a_\d+>(.*?)</a_\d+>', block, re.DOTALL | re.IGNORECASE)
        answers = [a.strip() for a in answers]

        out[qid] = {
            'id': qid,
            'question': question_clean,
            'type': q_type,
            'right': q_right,
            'answers': answers
        }
    return out

def build_grouped_questions(questions_dict: Dict[str, dict]) -> Dict[str, dict]:
    """
    Одна логическая группа 'Все вопросы'.
    """
    group_data = {'group_name': 'Все вопросы', 'questions': []}
    for qid, q in questions_dict.items():
        group_data['questions'].append({
            'id': qid,
            'question': q['question'],
            'type': q['type'],
            'right': q['right'],
            'answers': q['answers'],
        })
    return {'0': group_data}
