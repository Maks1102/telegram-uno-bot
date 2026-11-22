"""Markdown от локальной модели -> разметка Telegram (HTML).

Модель отвечает «обычным» Markdown (GitHub-стиль): **жирный**, *курсив*,
`код`, ## заголовки, списки, таблицы. Telegram принимает либо голый текст,
либо собственный HTML — поэтому ответ конвертируется в HTML и уходит с
parse_mode="HTML". Если Telegram всё равно отвергнет сообщение, handlers
отправляют текст, очищенный strip_tags() (см. handlers._answer).

Правила конвертации:
* сначала вырезаются блоки ```код``` — их содержимое не разбирается;
* &, <, >, " экранируются — иначе Telegram отвергнет сообщение целиком;
* блочная разметка (заголовки, списки, цитаты, таблицы) — построчно;
* внутри строки работают инлайн-правила (жирный, курсив, код, ссылки);
* непарные `**`, которые модели оставляют, просто удаляются.
"""

from __future__ import annotations

import html
import re

#: Лимит сообщения Telegram, символов.
LIMIT = 4096

#: Запас до лимита при резке — на закрывающие и повторные открывающие теги.
_MARGIN = 256

_CODE_BLOCK = re.compile(r"```[ \t]*[A-Za-z0-9_+-]*\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
_STRIKE = re.compile(r"~~(.+?)~~", re.S)
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<![\w])_([^_\n]+)_(?![\w])")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_HEADER = re.compile(r"^#{1,6}\s*(.*)$")
_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^(\s*)>\s?(.*)$")
_TABLE_SEP = re.compile(r"^[\s|:-]+$")
_ESCAPED = re.compile(r"\\([\\`*_[\]{}()#+\-.!|<>~])")
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)\b[^<>]*>")
_TOKEN = re.compile(r"\x00(\d+)\x00")


def md_to_html(text: str) -> str:
    """Превращает Markdown-ответ модели в HTML, понятный Telegram."""
    if not text or not text.strip():
        return ""

    blocks: list[str] = []

    def _stash_block(m: re.Match[str]) -> str:
        code = m.group(1).strip("\n")
        blocks.append(f"<pre>{html.escape(code)}</pre>")
        return f"\n\x00{len(blocks) - 1}\x00\n"

    body = _CODE_BLOCK.sub(_stash_block, text)
    body = html.escape(body)  # &, <>, " -> сущности
    body = _ESCAPED.sub(r"\1", body)  # \* и прочие экранирования модели

    lines = [_convert_line(line, blocks) for line in body.split("\n")]
    result = "\n".join(lines)
    result = _TOKEN.sub(lambda m: blocks[int(m.group(1))], result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def strip_tags(text: str) -> str:
    """Убирает HTML-разметку: запасной вариант, если Telegram отверг сообщение.

    Сначала удаляются сами теги, и только потом снимаются сущности — иначе
    «5 &lt; 6» превратится в «5 < 6», и этот `< 6 ...` снова съестся как тег.
    """
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def split_html(text: str, limit: int = LIMIT) -> list[str]:
    """Режет HTML на части ≤ лимита, не разрывая теги и не оставляя «висячих»."""
    if len(text) <= limit:
        return [text]

    budget = max(limit - _MARGIN, limit // 2)
    parts: list[str] = []
    rest = text
    while len(rest) > budget:
        cut = _safe_cut(rest, budget) or budget
        piece, rest = rest[:cut], rest[cut:].lstrip("\n")
        opened = _open_tags(piece)
        # тег без содержимого в конце куска переносим в следующий
        while opened:
            name, tag, start = opened[-1]
            if piece[start + len(tag) :].strip():
                break
            piece = piece[:start]
            opened.pop()
        if opened:
            piece += "".join(f"</{name}>" for name, _, _ in reversed(opened))
            if rest.strip():
                rest = "".join(tag for _, tag, _ in opened) + rest
            else:
                rest = ""
        if piece.strip():
            parts.append(piece)
    if rest.strip():
        parts.append(rest)
    return parts or [text[:limit]]


def _wrap(tag: str, content: str | None) -> str:
    """Оборачивает содержимое в тег; пустое содержимое не оборачивается."""
    if not content or not content.strip():
        return content or ""
    name = tag.split()[0]
    return f"<{tag}>{content}</{name}>"


def _inline(s: str, blocks: list[str]) -> str:
    """Инлайн-разметка внутри одной строки (после экранирования HTML)."""

    def _stash(m: re.Match[str]) -> str:
        blocks.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(blocks) - 1}\x00"

    s = _INLINE_CODE.sub(_stash, s)
    s = _BOLD.sub(lambda m: _wrap("b", m.group(1) or m.group(2)), s)
    s = _STRIKE.sub(lambda m: _wrap("s", m.group(1)), s)
    s = _ITALIC.sub(lambda m: _wrap("i", m.group(1) or m.group(2)), s)
    s = _LINK.sub(lambda m: _wrap(f'a href="{m.group(2)}"', m.group(1)), s)
    return s.replace("**", "")  # непарные звёздочки от модели


def _indent(raw: str) -> str:
    """Превращает пробелы/табы отступа в два пробела на уровень вложенности."""
    return "  " * (len(raw.replace("\t", "  ")) // 2)


def _convert_line(line: str, blocks: list[str]) -> str:
    """Блочная разметка одной строки; внутри — инлайн-правила."""
    if _HR.match(line):
        return "———"
    if _TABLE_SEP.match(line) and "-" in line:
        return ""  # разделитель строки таблицы |---|---|
    m = _HEADER.match(line)
    if m:
        return _wrap("b", _inline(m.group(1), blocks))
    m = _QUOTE.match(line)
    if m:
        inner = _inline(m.group(2), blocks)
        return f"<blockquote>{inner}</blockquote>" if inner.strip() else "┃"
    stripped = line.strip()
    if len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|"):
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        return _inline(" │ ".join(cells), blocks)
    m = _UL.match(line)
    if m:
        return f"{_indent(m.group(1))}• {_inline(m.group(2), blocks)}"
    m = _OL.match(line)
    if m:
        return f"{_indent(m.group(1))}{m.group(2)}. {_inline(m.group(3), blocks)}"
    return _inline(line, blocks)


def _safe_cut(s: str, budget: int) -> int:
    """Точка реза ≤ бюджета: не внутри тега, по возможности — граница абзаца."""
    in_tag = False
    last_safe = 0
    for i, ch in enumerate(s[:budget]):
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
            last_safe = i + 1
    if last_safe <= 0:
        last_safe = budget
    window = s[:last_safe]
    for sep in ("\n\n", "\n"):
        idx = window.rfind(sep)
        if idx > 0:
            return idx
    return last_safe


def _open_tags(text: str) -> list[tuple[str, str, int]]:
    """Незакрытые теги в куске: (имя, полный открывающий тег, позиция)."""
    stack: list[tuple[str, str, int]] = []
    for m in _TAG.finditer(text):
        closing, name = m.group(1), m.group(2).lower()
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i:]
                    break
        else:
            stack.append((name, m.group(0), m.start()))
    return stack
