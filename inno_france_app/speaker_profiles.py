from __future__ import annotations

import re
from typing import Any

from .text_utils import parse_speaker_lines, trim_text


SPEAKER_TAG_RE = re.compile(r"^SPEAKER(\d+)$")


def build_speaker_configs(translated_text: str) -> list[dict[str, Any]]:
    speaker_lines = parse_speaker_lines(translated_text)
    if not speaker_lines:
        return [
            {
                "speaker_tag": "[SPEAKER0]",
                "design_text": "大家好，欢迎收听本期节目。",
                "design_instruct": "Neutral, clear Mandarin voice, steady pace.",
                "language": "Chinese",
            }
        ]

    configs: list[dict[str, Any]] = []
    ordered_speakers = sorted(speaker_lines.keys(), key=_speaker_sort_key)
    for index, speaker in enumerate(ordered_speakers):
        lines = speaker_lines[speaker]
        sample_text = _build_sample_text(lines)
        avg_len = sum(len(line) for line in lines) / max(1, len(lines))
        question_ratio = _question_ratio(lines)
        instruct = _build_instruct(avg_len, question_ratio)
        configs.append(
            {
                "speaker_tag": f"[{speaker}]",
                "design_text": sample_text,
                "design_instruct": instruct,
                "language": "Chinese",
            }
        )

    return configs


def _speaker_sort_key(speaker: str) -> int:
    match = SPEAKER_TAG_RE.match(speaker)
    if match:
        return int(match.group(1))
    return 0


def _build_sample_text(lines: list[str]) -> str:
    if not lines:
        return "大家好，欢迎收听本期节目。"
    combined = " ".join(lines[:2]).strip()
    if not combined:
        combined = lines[0].strip() if lines else ""
    if not combined:
        combined = "大家好，欢迎收听本期节目。"
    return trim_text(combined, 160)


def _question_ratio(lines: list[str]) -> float:
    if not lines:
        return 0.0
    question_hits = 0
    for line in lines:
        if "?" in line or "？" in line or "吗" in line:
            question_hits += 1
    return question_hits / max(1, len(lines))

import random

def _build_instruct(avg_len: float, question_ratio: float) -> str:
    personas = [
        "年轻男性科技解说，20多岁，语速偏快，声音清亮偏洪亮，理性分析型表达。",
        "中年女性教师，40岁左右，语速适中，声音温和稳定，循循善诱的讲解风格。",
        "年长男性学者，60岁左右，语速较慢，声音略显沙哑，偏学术与思辨。",
        "年轻女性生活方式主播，20多岁，语速快，声音明快活泼，情绪感染力强。",
        "男性新闻播报员，30多岁，语速稳定，声音低沉有力，权威客观的表达方式。",
        "女性电台播客主持，30多岁，语速中等，略带沙哑音色，亲切自然的对话感。",
        "男性销售演示讲师，30岁出头，语速较快，声音洪亮，自信且富有煽动性。",
        "中年女性医疗从业者，40多岁，语速偏慢，声音柔和但坚定，专业且安抚型。",
        "男性纪录片旁白，50岁左右，语速较慢，声音低沉厚实，叙事感强。",
        "年轻女性辩论型学生，20岁出头，语速快，声音清晰锐利，逻辑性强。",
        "中年男性产品经理，40岁左右，语速适中，声音平实，结构化、条理清晰。",
        "女性心理咨询师，30多岁，语速偏慢，声音柔软温暖，共情与引导并重。",
        "男性财经评论员，40多岁，语速中快，声音稳重，偏数据与判断驱动。",
        "年轻男性娱乐解说，20多岁，语速很快，声音明亮，情绪外放、节奏感强。",
        "女性知识型UP主，30岁左右，语速适中，声音清晰干净，讲解通俗易懂。",
        "中年男性管理者，50岁左右，语速偏慢，声音低沉有压迫感，决策导向。",
        "年轻女性新闻记者，20多岁，语速中快，声音干脆利落，信息密度高。",
        "男性培训讲师，40岁左右，语速有节奏变化，声音洪亮，强调重点。",
        "女性纪录类旁白，40多岁，语速偏慢，声音温润，画面感和叙述感强。",
        "年长女性文化学者，60岁左右，语速缓慢，声音略沙哑，沉稳且富有深度。",
    ]

    persona = random.choice(personas)

    if question_ratio >= 0.35:
        base = "整体语气偏引导，多使用提问式表达。"
    elif avg_len >= 80:
        base = "表达偏长，注重完整论述与逻辑展开。"
    elif avg_len <= 30:
        base = "表达简短有力，节奏明快，信息集中。"
    else:
        base = "自然对话式表达，语气平衡放松。"

    return f"{persona}{base}"
