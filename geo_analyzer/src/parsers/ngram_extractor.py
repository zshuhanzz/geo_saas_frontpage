"""
N-gram Candidate Extractor (Phase 6 — Suggestions 系统 MVP backup)
=================================================================

纯算法,~30 行核心逻辑,在 LLM Batch 不可用 / 成本不允许时启用。

算法:
1. Tokenize response text by whitespace(保留原大小写 + 标点边界)。
2. 生成连续 2-5 词 n-gram。
3. Heuristic filter:
    - 长度 >= 4 字符
    - 含数字 **或** 含连字符(-)**或** 每个 word 首字母大写(PascalCase 迹象)
    - 不全是 stopwords
4. 排除:候选串(lowercase)在 ``known_variants`` 或 ``known_aliases``(flat
   lowercase set)内即已被覆盖。
5. 按 candidate_string 聚合:`frequency` 累加,`sample_position` 保留首次出现位置。

返回:list of {candidate_string, frequency, sample_position}。

不写 DB —— 调用方(CLI job / 主 pipeline)负责 UPSERT 到
``geo_settings_candidates``。保持可选:不在 main.py 默认接入。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set


# 轻量英文 stopword list;命中即过滤。中文 / 其他语言因无 whitespace 边界
# 天然不会被 n-gram 抽出来,所以这张表只覆盖 EN。
_STOPWORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "of", "in", "on", "at", "to", "for", "with",
    "by", "from", "as", "that", "this", "these", "those", "it", "its",
    "you", "your", "yours", "we", "our", "ours", "they", "their", "theirs",
    "i", "me", "my", "mine", "he", "she", "his", "her", "hers", "him",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "should", "may", "might", "must", "shall",
    "not", "no", "if", "then", "than", "so", "because", "when", "where",
    "what", "which", "who", "whom", "how", "why", "all", "any", "some",
    "each", "every", "other", "another", "such", "only", "own", "same",
    "about", "above", "below", "between", "into", "through", "during",
    "before", "after", "while",
}

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-']*")
_MIN_LEN = 4
_MAX_NGRAM = 5
_MIN_NGRAM = 2


def _tokens_with_positions(text: str) -> List[tuple]:
    """Return list of (token, start_char_index) tuples preserving source order."""
    return [(m.group(0), m.start()) for m in _WORD_RE.finditer(text or "")]


def _passes_heuristic(candidate: str) -> bool:
    """Must be >= 4 chars AND (has digit OR has hyphen OR all-word-first-upper)."""
    if len(candidate) < _MIN_LEN:
        return False
    has_digit = any(ch.isdigit() for ch in candidate)
    has_hyphen = "-" in candidate
    words = candidate.split()
    # 全部 word 首字母大写(PascalCase / TitleCase)且至少 1 个 word >= 2 字符
    first_upper = (
        len(words) > 0
        and all(w and w[0].isupper() for w in words)
        and any(len(w) >= 2 for w in words)
    )
    if not (has_digit or has_hyphen or first_upper):
        return False
    # 排除全是 stopwords 的组合(小写比对)
    low_words = [w.lower() for w in words]
    if all(w in _STOPWORDS for w in low_words):
        return False
    return True


def extract_ngram_candidates(
    text: str,
    known_variants: Iterable[str],
    known_aliases: Iterable[str],
) -> List[Dict]:
    """Extract n-gram candidate strings not yet in known config.

    Args:
        text: raw response text(可含 Markdown / 标点)
        known_variants: flat iterable of already-configured product match_variants
        known_aliases: flat iterable of already-configured brand/peer aliases +
                       primary names

    Returns:
        List of {"candidate_string": str, "frequency": int,
                 "sample_position": int} sorted by frequency desc then position asc.
        ``sample_position`` is the 0-indexed character offset of the first
        occurrence in ``text``.
    """
    if not text:
        return []

    known_lc: Set[str] = set()
    for v in known_variants:
        if v:
            known_lc.add(v.strip().lower())
    for a in known_aliases:
        if a:
            known_lc.add(a.strip().lower())

    tokens = _tokens_with_positions(text)
    if not tokens:
        return []

    # candidate_string (as-seen, stripped) -> {"frequency": int, "sample_position": int}
    agg: Dict[str, Dict] = {}

    for n in range(_MIN_NGRAM, _MAX_NGRAM + 1):
        for i in range(len(tokens) - n + 1):
            window = tokens[i:i + n]
            joined = " ".join(t for t, _ in window).strip()
            if not joined:
                continue
            if joined.lower() in known_lc:
                continue
            if not _passes_heuristic(joined):
                continue
            slot = agg.get(joined)
            if slot is None:
                agg[joined] = {"frequency": 1, "sample_position": window[0][1]}
            else:
                slot["frequency"] += 1
                # 保留首次出现位置;sample_position 永远不更新

    out = [
        {
            "candidate_string": k,
            "frequency": v["frequency"],
            "sample_position": v["sample_position"],
        }
        for k, v in agg.items()
    ]
    out.sort(key=lambda x: (-x["frequency"], x["sample_position"]))
    return out
