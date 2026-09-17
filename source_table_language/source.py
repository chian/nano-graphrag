"""Addressable source and table views used by the table language."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from collections import Counter
from typing import Callable, Sequence

from .types import SourceCell, SourceLine, SourceRow, SourceSpan, TableRegion


_HTML_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.I | re.S)
_HTML_ROW_RE = re.compile(r"<tr\b[^>]*>.*?</tr\s*>", re.I | re.S)
_HTML_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", re.I | re.S)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_FIXED_COLUMN_RE = re.compile(r"\s{2,}")
_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s+|[A-Z][A-Z0-9 ,.:'()/&-]{4,})")
_MARKER_RE = re.compile(r"(?:\*{1,3}|[†‡§]|\[[A-Za-z0-9]{1,3}\])")


def _stable_id(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def source_lines(text: str) -> tuple[SourceLine, ...]:
    lines: list[SourceLine] = []
    offset = 0
    for raw in str(text).splitlines(keepends=True):
        content = raw.rstrip("\r\n")
        lines.append(SourceLine(content, offset, offset + len(content)))
        offset += len(raw)
    if offset < len(text):
        lines.append(SourceLine(text[offset:], offset, len(text)))
    return tuple(lines)


def _line_blocks(
    lines: Sequence[SourceLine],
    predicate: Callable[[str], bool],
) -> tuple[tuple[SourceLine, ...], ...]:
    blocks: list[tuple[SourceLine, ...]] = []
    current: list[SourceLine] = []
    for line in lines:
        if predicate(line.text):
            current.append(line)
        elif current:
            blocks.append(tuple(current))
            current = []
    if current:
        blocks.append(tuple(current))
    return tuple(blocks)


def _markdown_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return len(cells) >= 2 and all(
        bool(_MARKDOWN_SEPARATOR_CELL_RE.fullmatch(cell)) for cell in cells
    )


def _stable_width(
    block: Sequence[SourceLine],
    splitter: Callable[[str], Sequence[str]],
) -> bool:
    widths: list[int] = []
    for line in block:
        try:
            widths.append(len(tuple(splitter(line.text))))
        except (csv.Error, ValueError):
            return False
    useful = [width for width in widths if width >= 2]
    if len(useful) < 3:
        return False
    modal = Counter(useful).most_common(1)[0][1]
    return modal / len(useful) >= 0.75


def _make_region(
    kind: str,
    text: str,
    lines: Sequence[SourceLine],
) -> TableRegion:
    start = lines[0].start_offset
    end = lines[-1].end_offset
    region_text = text[start:end]
    return TableRegion(
        region_id=_stable_id(
            {"kind": kind, "start": start, "end": end, "text": region_text}
        ),
        parser_hint=kind,
        start_offset=start,
        end_offset=end,
        text=region_text,
        lines=tuple(lines),
    )


def discover_table_regions(text: str) -> tuple[TableRegion, ...]:
    """Find non-overlapping regions with measurable table structure."""

    source = str(text)
    lines = source_lines(source)
    candidates: list[tuple[int, TableRegion]] = []

    for match in _HTML_TABLE_RE.finditer(source):
        rows = tuple(_HTML_ROW_RE.finditer(match.group(0)))
        if len(rows) < 2:
            continue
        region_lines = tuple(
            SourceLine(
                text=row.group(0),
                start_offset=match.start() + row.start(),
                end_offset=match.start() + row.end(),
            )
            for row in rows
        )
        candidates.append((0, _make_region("html", source, region_lines)))

    for block in _line_blocks(lines, lambda value: value.count("|") >= 2):
        if len(block) >= 2 and any(_markdown_separator(line.text) for line in block):
            candidates.append((1, _make_region("markdown", source, block)))

    for block in _line_blocks(lines, lambda value: value.count("\t") >= 1):
        if len(block) >= 3 and _stable_width(block, lambda value: value.split("\t")):
            candidates.append((2, _make_region("tab", source, block)))

    for delimiter, kind, priority in ((",", "csv", 3), (";", "semicolon", 4)):
        for block in _line_blocks(
            lines, lambda value, token=delimiter: value.count(token) >= 2
        ):
            if len(block) >= 4 and _stable_width(
                block,
                lambda value, token=delimiter: next(
                    csv.reader([value], delimiter=token)
                ),
            ):
                candidates.append((priority, _make_region(kind, source, block)))

    for block in _line_blocks(
        lines,
        lambda value: len(_FIXED_COLUMN_RE.split(value.strip())) >= 3,
    ):
        if len(block) >= 4 and _stable_width(
            block, lambda value: _FIXED_COLUMN_RE.split(value.strip())
        ):
            candidates.append((5, _make_region("fixed_width", source, block)))

    selected: list[TableRegion] = []
    for _priority, region in sorted(
        candidates,
        key=lambda item: (item[1].start_offset, item[0], -len(item[1].text)),
    ):
        if any(
            region.start_offset < existing.end_offset
            and existing.start_offset < region.end_offset
            for existing in selected
        ):
            continue
        selected.append(region)
    return tuple(sorted(selected, key=lambda item: item.start_offset))


def text_without_table_regions(
    text: str,
    regions: Sequence[TableRegion],
) -> str:
    characters = list(str(text))
    for region in regions:
        for index in range(region.start_offset, min(region.end_offset, len(characters))):
            if characters[index] not in "\r\n":
                characters[index] = " "
    return "".join(characters)


def _html_cell(value: str) -> str:
    return " ".join(html.unescape(_HTML_TAG_RE.sub("", value)).split())


def _cells_from_line(
    line: SourceLine,
    values: Sequence[str],
) -> tuple[SourceCell, ...]:
    cells: list[SourceCell] = []
    cursor = 0
    for column_index, value in enumerate(values):
        cleaned = str(value).strip()
        if not cleaned:
            cells.append(
                SourceCell(column_index, "", line.start_offset + cursor, line.start_offset + cursor)
            )
            continue
        position = line.text.find(cleaned, cursor)
        if position < 0:
            position = line.text.find(cleaned)
        if position < 0:
            position = cursor
        end = position + len(cleaned)
        cells.append(
            SourceCell(
                column_index=column_index,
                text=cleaned,
                start_offset=line.start_offset + position,
                end_offset=line.start_offset + min(end, len(line.text)),
            )
        )
        cursor = max(cursor, end)
    return tuple(cells)


def grid_rows(region: TableRegion, parser_kind: str) -> tuple[SourceRow, ...]:
    rows: list[SourceRow] = []
    if parser_kind == "html":
        for row_index, match in enumerate(_HTML_ROW_RE.finditer(region.text)):
            cells: list[SourceCell] = []
            for column_index, cell_match in enumerate(
                _HTML_CELL_RE.finditer(match.group(0))
            ):
                cells.append(
                    SourceCell(
                        column_index=column_index,
                        text=_html_cell(cell_match.group(1)),
                        start_offset=(
                            region.start_offset
                            + match.start()
                            + cell_match.start(1)
                        ),
                        end_offset=(
                            region.start_offset
                            + match.start()
                            + cell_match.end(1)
                        ),
                    )
                )
            if cells:
                start = region.start_offset + match.start()
                end = region.start_offset + match.end()
                rows.append(
                    SourceRow(
                        row_id=_stable_id(
                            {"region": region.region_id, "row": row_index, "text": match.group(0)}
                        ),
                        row_index=row_index,
                        raw_text=match.group(0),
                        start_offset=start,
                        end_offset=end,
                        cells=tuple(cells),
                    )
                )
        return tuple(rows)

    for row_index, line in enumerate(region.lines):
        raw = line.text
        if parser_kind == "markdown":
            if _markdown_separator(raw):
                continue
            values = tuple(cell.strip() for cell in raw.strip().strip("|").split("|"))
        elif parser_kind == "tab":
            values = tuple(cell.strip() for cell in raw.split("\t"))
        elif parser_kind in {"csv", "semicolon"}:
            delimiter = "," if parser_kind == "csv" else ";"
            values = tuple(
                cell.strip() for cell in next(csv.reader([raw], delimiter=delimiter))
            )
        elif parser_kind == "fixed_width":
            values = tuple(cell.strip() for cell in _FIXED_COLUMN_RE.split(raw.strip()))
        else:
            raise ValueError(f"unsupported table parser kind {parser_kind!r}")
        if len(values) < 2:
            continue
        cells = _cells_from_line(line, values)
        rows.append(
            SourceRow(
                row_id=_stable_id(
                    {"region": region.region_id, "row": row_index, "text": raw}
                ),
                row_index=row_index,
                raw_text=raw,
                start_offset=line.start_offset,
                end_offset=line.end_offset,
                cells=cells,
            )
        )
    return tuple(rows)


def _paragraphs(lines: Sequence[SourceLine]) -> tuple[tuple[SourceLine, ...], ...]:
    return _line_blocks(lines, lambda value: bool(value.strip()))


class TableWorkspace:
    """Inspectable, addressable view over one source table and its context."""

    def __init__(
        self,
        *,
        source_text: str,
        source_title: str,
        region: TableRegion,
    ) -> None:
        self.source_text = str(source_text)
        self.source_title = str(source_title or "")
        self.region = region
        self._lines = source_lines(self.source_text)
        self._spans = self._context_spans()

    @property
    def spans(self) -> dict[str, SourceSpan]:
        return {span.span_id: span for span in self._spans}

    def rows(self, parser_kind: str) -> tuple[SourceRow, ...]:
        return grid_rows(self.region, parser_kind)

    def show_table(self, parser_kind: str | None = None) -> dict[str, object]:
        kind = parser_kind or self.region.parser_hint
        rows = self.rows(kind)
        indexes = list(range(min(30, len(rows))))
        if len(rows) > 40:
            indexes.extend(range(len(rows) - 10, len(rows)))
        return {
            "region_id": self.region.region_id,
            "parser_hint": self.region.parser_hint,
            "row_count": len(rows),
            "rows": [rows[index].to_dict() for index in dict.fromkeys(indexes)],
        }

    def show_context(self) -> dict[str, object]:
        return {
            "document_title_hint": self.source_title,
            "spans": [span.to_dict() for span in self._spans],
        }

    def show_rows(
        self,
        first: int,
        last: int,
        parser_kind: str | None = None,
    ) -> list[dict[str, object]]:
        rows = self.rows(parser_kind or self.region.parser_hint)
        start = max(0, int(first))
        stop = min(len(rows), max(start, int(last) + 1))
        return [row.to_dict() for row in rows[start:stop]]

    def show_column(
        self,
        column: int,
        parser_kind: str | None = None,
    ) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for row in self.rows(parser_kind or self.region.parser_hint):
            if 0 <= int(column) < len(row.cells):
                out.append(
                    {
                        "row_id": row.row_id,
                        "row_index": row.row_index,
                        "cell": row.cells[int(column)].to_dict(),
                    }
                )
        return out

    def follow_marker(self, marker: str) -> list[dict[str, object]]:
        token = str(marker)
        if not token:
            return []
        return [
            span.to_dict()
            for span in self._spans
            if token in span.text
        ]

    def initial_view(self) -> dict[str, object]:
        return {
            "table": self.show_table(),
            "context": self.show_context(),
            "available_inspections": [
                "show_rows",
                "show_column",
                "follow_marker",
            ],
        }

    def _context_spans(self) -> tuple[SourceSpan, ...]:
        before = [line for line in self._lines if line.end_offset <= self.region.start_offset]
        after = [line for line in self._lines if line.start_offset >= self.region.end_offset]
        before_blocks = _paragraphs(before)
        after_blocks = _paragraphs(after)
        selected: list[tuple[str, tuple[SourceLine, ...]]] = []
        selected.extend(("before", block) for block in before_blocks[-3:])
        selected.extend(("after", block) for block in after_blocks[:5])

        markers = set(_MARKER_RE.findall(self.region.text))
        for block in (*before_blocks, *after_blocks):
            block_text = "\n".join(line.text for line in block)
            if markers and any(marker in block_text for marker in markers):
                selected.append(("marker_reference", block))
            elif len(block) == 1 and _HEADING_RE.match(block[0].text):
                selected.append(("heading", block))

        spans: dict[tuple[int, int], SourceSpan] = {}
        for kind, block in selected:
            if not block:
                continue
            start = block[0].start_offset
            end = block[-1].end_offset
            text = self.source_text[start:end]
            key = (start, end)
            existing = spans.get(key)
            if existing is not None and existing.kind != "marker_reference":
                continue
            spans[key] = SourceSpan(
                span_id=_stable_id(
                    {"region": self.region.region_id, "start": start, "end": end}
                ),
                kind=kind,
                start_offset=start,
                end_offset=end,
                text=text,
            )
        return tuple(sorted(spans.values(), key=lambda item: item.start_offset))
