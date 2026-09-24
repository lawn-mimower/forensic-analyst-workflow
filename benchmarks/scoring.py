"""
Scoring for both benchmarks. Pure functions, no LLM calls (see tests/test_benchmarks.py).

Question answering
    Each response is reduced to an answer span: the text after the last
    "ANSWER:" marker, up to the end of that line. When a response has no marker
    the last non-empty line is used and ``format_ok`` is False.

    number  The first number in the span (after dropping fiscal-year and date
            tokens) must equal the gold value to the precision it is written
            with: |answer - gold| <= half a unit in its last decimal place, and
            never less than 0.005 (gold values have two decimals). So 4386,
            4386.4 and 4386.40 all match 4386.40, while 51.35 does not match
            51.15. "crore" in the span converts crores to lakhs, a value more
            than 1,000x the gold is read as rupees, and for percentages a value
            of at most 1.5 is also read as a fraction.
    text    After normalisation (case, punctuation, "&" -> "and", honorifics
            such as Mr/Mrs dropped) one of the gold aliases must appear in the span.
    date    The span must contain the gold date (several common formats).

    ``lenient`` is a diagnostic only: whether the gold answer appears anywhere
    in the full response under the same matching rules.

Issue detection
    Flags and planted issues are sets of (company, issue_type) pairs; precision,
    recall and F1 are micro-averaged over those pairs.
"""

from __future__ import annotations

import datetime as dt
import re

_ANSWER_RE = re.compile(r"ANSWER\s*[:：]\s*(.*)", re.IGNORECASE)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9

# Tokens that contain digits but are not answers: fiscal years, dates, note numbers
_NOISE_RE = re.compile(
    r"\bFY\s*\d{4}(?:\s*[-–/]\s*\d{2,4})?"
    r"|\b\d{4}\s*[-–]\s*\d{2}\b(?!\.\d)"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")[a-z]*\.?,?\s+\d{4}"
    r"|\b(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\bnote\s+\d+",
    re.IGNORECASE,
)
_NUM_RE = re.compile(r"(?<![\w])[-−]?\(?\d[\d,]*(?:\.\d+)?\)?")
_HONORIFICS = {"mr", "mrs", "ms", "m s", "shri", "smt", "dr", "miss"}


def answer_span(response: str | None) -> tuple[str, bool]:
    """Return (span, format_ok)."""
    text = response or ""
    matches = list(_ANSWER_RE.finditer(text))
    if matches:
        span = matches[-1].group(1).strip()
        span = span.strip("*_` ").strip()
        return span, True
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else ""), False


def _numbers_with_places(text: str) -> list[tuple[float, int]]:
    """(value, decimal places) for each number, in reading order, ignoring
    fiscal-year, date and note tokens."""
    cleaned = _NOISE_RE.sub(" ", text or "")
    out = []
    for m in _NUM_RE.finditer(cleaned):
        tok = m.group(0)
        neg = tok.startswith(("-", "−")) or (tok.startswith("(") and tok.endswith(")"))
        tok = tok.strip("()-−").replace(",", "")
        if not tok or tok == ".":
            continue
        try:
            v = float(tok)
        except ValueError:
            continue
        places = len(tok.split(".", 1)[1]) if "." in tok else 0
        out.append((-v if neg else v, places))
    return out


def numbers_in(text: str) -> list[float]:
    """Numbers in reading order, ignoring fiscal-year, date and note tokens."""
    return [v for v, _ in _numbers_with_places(text)]


def number_matches(span: str, gold: float, unit: str = "lakhs", *, first_only: bool = True) -> bool:
    nums = _numbers_with_places(span)
    if not nums:
        return False
    low = span.lower()
    for v, places in (nums[:1] if first_only else nums):
        half_unit = 0.5 * 10 ** (-places)
        cands = [(v, 1.0)]  # (value in the gold unit, scale of the written precision)
        if unit == "lakhs":
            if "crore" in low:
                cands.append((v * 100, 100.0))
            if abs(v) > 1000 * max(abs(gold), 0.01):
                cands.append((v / 1e5, 1e-5))
        elif unit == "percent" and abs(v) <= 1.5 and abs(gold) > 1.5:
            cands.append((v * 100, 100.0))
        for value, scale in cands:
            if abs(value - gold) <= max(0.005, half_unit * scale) + 1e-9:
                return True
    return False


def normalise_text(text: str) -> str:
    t = (text or "").lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    words = [w for w in t.split()]
    # drop honorifics ("m s" is how "M/s" normalises)
    out, i = [], 0
    while i < len(words):
        if i + 1 < len(words) and f"{words[i]} {words[i + 1]}" in _HONORIFICS:
            i += 2
            continue
        if words[i] in _HONORIFICS:
            i += 1
            continue
        out.append(words[i])
        i += 1
    return " ".join(out)


def text_matches(span: str, aliases: list[str]) -> bool:
    norm = f" {normalise_text(span)} "
    return any(f" {normalise_text(a)} " in norm for a in aliases if normalise_text(a))


def dates_in(text: str) -> set[dt.date]:
    found: set[dt.date] = set()
    t = (text or "").lower()
    month_alt = "|".join(sorted(_MONTHS, key=len, reverse=True))
    for d, mon, y in re.findall(r"(\d{1,2})(?:st|nd|rd|th)?\s+(" + month_alt + r")[a-z]*\.?,?\s+(\d{4})", t):
        found.add(_safe_date(int(y), _MONTHS[mon], int(d)))
    for mon, d, y in re.findall(r"(" + month_alt + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t):
        found.add(_safe_date(int(y), _MONTHS[mon], int(d)))
    for y, m, d in re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        found.add(_safe_date(int(y), int(m), int(d)))
    for d, m, y in re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", t):
        found.add(_safe_date(int(y), int(m), int(d)))  # Indian day-first order
    found.discard(None)
    return found


def _safe_date(y: int, m: int, d: int):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def score_answer(question: dict, response: str | None) -> dict:
    """Score one response. Returns {correct, lenient, format_ok, span}."""
    span, format_ok = answer_span(response)
    kind = question["answer_type"]
    full = response or ""
    if kind == "number":
        correct = number_matches(span, question["gold"], question.get("unit", "lakhs"))
        lenient = number_matches(full, question["gold"], question.get("unit", "lakhs"), first_only=False)
    elif kind == "text":
        correct = text_matches(span, question["aliases"])
        lenient = text_matches(full, question["aliases"])
    elif kind == "date":
        gold = dt.date.fromisoformat(question["gold"])
        correct = gold in dates_in(span)
        lenient = gold in dates_in(full)
    else:
        raise ValueError(f"unknown answer_type {kind!r}")
    return {"correct": bool(correct), "lenient": bool(lenient or correct), "format_ok": format_ok,
            "span": span[:300]}


def parsed_answer(question: dict, span: str) -> str | None:
    """The value a span was scored on, in a compact form (number, normalised text or ISO date)."""
    kind = question["answer_type"]
    if kind == "number":
        nums = numbers_in(span)
        return f"{nums[0]:.3f}" if nums else None
    if kind == "date":
        found = sorted(dates_in(span))
        return found[0].isoformat() if found else None
    return normalise_text(span)[:80] or None


def precision_recall(flags: set[tuple[str, str]], gold: set[tuple[str, str]]) -> dict:
    tp = len(flags & gold)
    fp = len(flags - gold)
    fn = len(gold - flags)
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _r(p), "recall": _r(r), "f1": _r(f1)}


def _r(x):
    return None if x is None else round(x, 3)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def summarise_qa(items: list[dict]) -> dict:
    """Accuracy and cost summary for one system's scored items."""
    n = len(items)
    if not n:
        return {"n": 0}
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)

    def acc(xs, key="correct"):
        return round(sum(bool(x[key]) for x in xs) / len(xs), 3)

    lat = sorted(x["latency_s"] for x in items)
    return {
        "n": n,
        "correct": sum(bool(x["correct"]) for x in items),
        "accuracy": acc(items),
        "accuracy_95ci": wilson_interval(sum(bool(x["correct"]) for x in items), n),
        "lenient_accuracy": acc(items, "lenient"),
        "format_ok_rate": acc(items, "format_ok"),
        "by_category": {c: {"n": len(xs), "accuracy": acc(xs)} for c, xs in sorted(by_cat.items())},
        "llm_calls_per_q": round(sum(x["llm_calls"] for x in items) / n, 2),
        "prompt_tokens_per_q": round(sum(x["prompt_tokens_est"] for x in items) / n),
        "completion_tokens_per_q": round(sum(x["completion_tokens_est"] for x in items) / n),
        "latency_median_s": round(lat[n // 2] if n % 2 else (lat[n // 2 - 1] + lat[n // 2]) / 2, 1),
        "latency_mean_s": round(sum(lat) / n, 1),
    }
