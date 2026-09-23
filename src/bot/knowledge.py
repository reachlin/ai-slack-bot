"""Keyword (BM25) search over a folder of markdown files, chunked by heading."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]+")
WORD = re.compile(r"[^\W_]+")
MAX_CHUNK_CHARS = 1500
K1, B = 1.5, 0.75


def tokenize(text: str) -> list[str]:
    """Lowercased words, plus character bigrams for CJK text (which has no spaces)."""
    text = text.lower()
    tokens = []
    for run in CJK.findall(text):
        tokens += [run] if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)]
    tokens += WORD.findall(CJK.sub(" ", text))
    return tokens


@dataclass(frozen=True)
class Chunk:
    source: str  # path relative to the knowledge folder
    heading: str  # heading trail, e.g. "Deploy › Rollback"
    text: str

    @property
    def citation(self) -> str:
        return f"{self.source} › {self.heading}" if self.heading else self.source


def _split_long(body: str) -> list[str]:
    parts, current = [], ""
    for para in body.split("\n\n"):
        while len(para) > MAX_CHUNK_CHARS:
            if current:
                parts.append(current)
                current = ""
            parts.append(para[:MAX_CHUNK_CHARS])
            para = para[MAX_CHUNK_CHARS:]
        if current and len(current) + len(para) + 2 > MAX_CHUNK_CHARS:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current.strip():
        parts.append(current)
    return parts


def chunk_markdown(source: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    trail: list[str] = []
    lines: list[str] = []
    in_fence = False

    def flush():
        body = "\n".join(lines).strip()
        lines.clear()
        if body:
            chunks.extend(Chunk(source, " › ".join(trail), part) for part in _split_long(body))

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line)
        if match:
            flush()
            trail[len(match[1]) - 1 :] = [match[2]]
        else:
            lines.append(line)
    flush()
    return chunks


class KnowledgeBase:
    """Indexes every *.md under `root`; re-indexes automatically when files change."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._stamp: tuple | None = None
        self.chunks: list[Chunk] = []
        self._tfs: list[Counter] = []
        self._lens: list[int] = []
        self._df: Counter = Counter()
        self._avg_len = 0.0

    def _files(self) -> list[Path]:
        return sorted(self.root.rglob("*.md")) if self.root.is_dir() else []

    def refresh(self) -> None:
        files = self._files()
        stamp = tuple((str(p), p.stat().st_mtime_ns) for p in files)
        if stamp == self._stamp:
            return
        self._stamp = stamp
        self.chunks = [
            chunk
            for path in files
            for chunk in chunk_markdown(
                str(path.relative_to(self.root)), path.read_text(encoding="utf-8", errors="replace")
            )
        ]
        docs = [tokenize(f"{c.heading}\n{c.text}") for c in self.chunks]
        self._tfs = [Counter(d) for d in docs]
        self._lens = [len(d) for d in docs]
        self._df = Counter(term for tf in self._tfs for term in tf)
        self._avg_len = sum(self._lens) / len(docs) if docs else 0.0

    def is_empty(self) -> bool:
        self.refresh()
        return not self.chunks

    def search(self, query: str, k: int = 5) -> list[tuple[float, Chunk]]:
        self.refresh()
        terms = set(tokenize(query))
        n = len(self.chunks)
        scored = []
        for i, tf in enumerate(self._tfs):
            score = 0.0
            for term in terms:
                if f := tf.get(term):
                    df = self._df[term]
                    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                    norm = K1 * (1 - B + B * self._lens[i] / self._avg_len)
                    score += idf * f * (K1 + 1) / (f + norm)
            if score > 0:
                scored.append((score, self.chunks[i]))
        scored.sort(key=lambda s: s[0], reverse=True)
        return scored[:k]
