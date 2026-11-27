"""Locate image URL spans in card text so an edit preserves the surrounding text."""

import html
import re
from array import array
from bisect import bisect_right
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import cast
from urllib.parse import urlsplit

from lithica import registry
from lithica.modules.cards import card

MAX_LINKS = 500
MAX_URL_LENGTH = 2048

_REFERENCE = re.compile(r"lithica:post/([0-9]+)\Z")
_MARKDOWN_ESCAPE = re.compile(r"""\\([!-/:-@\[-`{-~])""")
_MARKDOWN_TOKEN = re.compile(r"\\[!-~]|!\[|[\[\]]|\n")
_LABEL = r"(?:\\[^\n]|[^\[\]\\\n]){1,999}"
_DEFINITION = re.compile(rf"(?m)^ {{0,3}}\[({_LABEL})\]:[ \t]*")
_IMAGE_DESTINATION = re.compile(r"\]\([ \t\r\n]*<?(?:https?|lithica|&)", re.IGNORECASE)
_BARE_DESTINATION = re.compile(r"""(?:\\[()]|[^\s<>"()\\]++|\\(?![()]))++""")
_LABEL_SUFFIX = re.compile(rf"\[({_LABEL})?\]")
_TITLE = r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\))"""
_LINK_END = re.compile(rf"(?:[ \t\r\n]+{_TITLE})?[ \t\r\n]*\)")
_DEFINITION_END = re.compile(rf"(?:[ \t]+{_TITLE})?[ \t]*\r?$", re.MULTILINE)
_CSS_TOKEN = re.compile(
    r"""(?<![\w-])url\(\s*(?:"([^"\n]*)"|'([^'\n]*)'|([^\s"'()]*))\s*\)"""
    r"""|/\*[^*]*(?:\*(?!/)[^*]*)*(?:\*/|\Z)"""
    r"""|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""",
    re.IGNORECASE,
)
_ENTITY = re.compile(r"&(?:#[xX][0-9a-fA-F]+;?|#[0-9]+;?|[A-Za-z][A-Za-z0-9]{0,31};?)")
_ATTRIBUTE = re.compile(r"""([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?""")
_TAG_NAME = re.compile(r"<[^\s/>]+")
_CANDIDATE = re.compile(r"[^\s,][^\s]*")
_DESCRIPTOR_TOKEN = re.compile(r"[(),]")
_CODE_RUN = re.compile(r"\\[\\`]|`+")
_FENCE = re.compile(r"(?m)^ {0,3}(`{3,}|~{3,})([^\n]*)\n?")


@dataclass(frozen=True)
class Link:
    start: int
    end: int
    url: str

    @property
    def reference(self) -> int | None:
        found = _REFERENCE.fullmatch(self.url)
        if found is None:
            return None
        return int(found[1])


def _url(value: str) -> str | None:
    value = value.strip()
    if len(value) > MAX_URL_LENGTH:
        return None
    if _REFERENCE.fullmatch(value):
        return value
    try:
        parts = urlsplit(value)
        if parts.scheme in ("http", "https") and parts.hostname:
            return value
    except ValueError:
        pass
    return None


def _link(
    text: str, start: int, end: int, *, markdown: bool = False, entities: bool = True
) -> Link | None:
    # Preserve whitespace even inside quoted attributes or CSS arguments.
    raw = text[start:end]
    value = _MARKDOWN_ESCAPE.sub(r"\1", raw) if markdown else raw
    value = _url(html.unescape(value) if entities else value)
    if value is None:
        return None
    return Link(start + len(raw) - len(raw.lstrip()), start + len(raw.rstrip()), value)


def _css(text: str, offset: int) -> Iterator[Link]:
    for match in _CSS_TOKEN.finditer(text):
        if match.lastindex is None:
            continue
        link = _link(text, *match.span(match.lastindex), entities=False)
        if link is not None:
            yield Link(offset + link.start, offset + link.end, link.url)


def _srcset(text: str, offset: int) -> Iterator[Link]:
    position = 0
    while (match := _CANDIDATE.search(text, position)) is not None:
        start, end = match.span()
        position = end
        while end > start and text[end - 1] == ",":
            end -= 1
        if (link := _link(text, start, end, entities=False)) is not None:
            yield Link(offset + link.start, offset + link.end, link.url)
        if end != position:
            continue
        # Descriptors end at a comma outside parentheses, or at EOF.
        parentheses = False
        for token in _DESCRIPTOR_TOKEN.finditer(text, position):
            if token[0] == "(":
                parentheses = True
            elif token[0] == ")":
                parentheses = False
            elif not parentheses:
                position = token.end()
                break
        else:
            break


def _attribute_links(
    text: str, offset: int, scan: Callable[[str, int], Iterator[Link]]
) -> Iterator[Link]:
    if "&" not in text:
        yield from scan(text, offset)
        return
    parts: list[str] = []
    starts: list[int] = []
    entities: list[tuple[int, int, int]] = []
    source = 0
    decoded = 0
    for entity in _ENTITY.finditer(text):
        value = html.unescape(entity[0])
        if value == entity[0]:
            continue
        decoded += entity.start() - source
        starts.append(decoded)
        parts.extend((text[source : entity.start()], value))
        decoded += len(value)
        source = entity.end()
        entities.append((decoded, entity.start(), source))

    def original(position: int, *, end: bool = False) -> int:
        index = bisect_right(starts, position) - 1
        if index < 0:
            return position
        decoded_end, source_start, source_end = entities[index]
        if position < decoded_end:
            return source_end if end and position > starts[index] else source_start
        return position + source_end - decoded_end

    for link in scan("".join([*parts, text[source:]]), 0):
        yield Link(
            offset + original(link.start),
            offset + original(link.end, end=True),
            link.url,
        )


class _Markup(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=False)
        self.line_offsets = array("I", [0])
        self.line_offsets.extend(match.end() for match in re.finditer("\n", text))
        self.links: list[Link] = []
        self.markup: list[tuple[int, int]] = []
        self.in_style = False
        # In HTML the marked section opener is a bogus comment. Avoid the
        # standard parser's XML-only assertion for unknown section keywords.
        self.feed(text.replace("<![", "<! "))
        self.close()

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = self.get_starttag_text()
        assert raw is not None
        name = _TAG_NAME.match(raw)
        assert name is not None
        offset = self.source_offset()
        self.markup.append((offset, offset + len(raw)))
        self.in_style = tag == "style"
        # HTMLParser gives decoded attributes without source spans. Read just
        # this tag's attributes again to keep the spelling of each URL's slot.
        seen: set[str] = set()
        for attr in _ATTRIBUTE.finditer(raw, name.end()):
            key = attr[1].lower()
            if key in seen:
                continue
            seen.add(key)
            group = next(
                (index for index in (2, 3, 4) if attr[index] is not None), None
            )
            if group is None:
                continue
            start, end = attr.span(group)
            if key == "style":
                self.links.extend(
                    _attribute_links(raw[start:end], offset + start, _css)
                )
            elif key == "srcset" and tag in ("img", "source"):
                self.links.extend(
                    _attribute_links(raw[start:end], offset + start, _srcset)
                )
            elif key == "src" and tag == "img":
                if (link := _link(raw, start, end)) is not None:
                    self.links.append(
                        Link(offset + link.start, offset + link.end, link.url)
                    )

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_style:
            offset = self.source_offset()
            self.markup.append((offset, offset + len(data)))
            self.links.extend(_css(data, offset))

    def handle_comment(self, data: str) -> None:
        offset = self.source_offset()
        self.markup.append((offset, offset + len(data) + len("<!---->")))


def _destination(text: str, start: int) -> tuple[int, int, int] | None:
    """The URL span and the position of the following title or delimiter."""
    while start < len(text) and text[start] in " \t\r\n":
        start += 1
    if start == len(text):
        return None
    if text[start] == "<":
        end = start + 1
        while end < len(text) and text[end] not in "<>\n\r":
            end += 1
        if end < len(text) and text[end] == ">":
            return start + 1, end, end + 1
        return None
    if text[start] not in "hHlL&\\":
        return None
    end = start
    depth = 0
    # Use the regex engine to move over runs of literal characters. Only
    # parentheses require a counter, with bounded lookahead on a near miss.
    limit = min(len(text), start + MAX_URL_LENGTH * 5)
    while end < limit:
        if literal := _BARE_DESTINATION.match(text, end, limit):
            end = literal.end()
        elif text[end] == "(":
            depth += 1
            end += 1
        elif text[end] == ")" and depth:
            depth -= 1
            end += 1
        else:
            break
    if end == limit and limit < len(text):
        return None
    return (start, end, end) if end > start and depth == 0 else None


def _label(text: str) -> str:
    return " ".join(text.split()).casefold()


def _fenced_code(text: str) -> Iterator[tuple[int, int]]:
    position = 0
    while (opening := _FENCE.search(text, position)) is not None:
        marker = opening[1]
        closing = re.compile(
            rf"(?m)^ {{0,3}}{marker[0]}{{{len(marker)},}}[ \t]*\r?$"
        ).search(text, opening.end())
        position = closing.end() if closing else len(text)
        yield opening.start(), position


def _inline_code(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    # Pair equal backtick runs in one pass from the right. Compact offsets
    # keep memory bounded even when nearly every character is a delimiter.
    offsets = array("I")
    for run in _CODE_RUN.finditer(text, start, end):
        if text[run.start()] == "`":
            offsets.extend(run.span())
    next_end: dict[int, int] = {}
    for index in range(len(offsets) - 2, -1, -2):
        first, last = offsets[index], offsets[index + 1]
        length = last - first
        offsets[index + 1] = next_end.get(length, 0)
        next_end[length] = last
    consumed = start
    for index in range(0, len(offsets), 2):
        first, last = offsets[index], offsets[index + 1]
        if first >= consumed and last:
            yield first, last
            consumed = last


def _code(text: str) -> Iterator[tuple[int, int]]:
    previous = 0
    for start, end in _fenced_code(text):
        yield from _inline_code(text, previous, start)
        yield start, end
        previous = end
    yield from _inline_code(text, previous, len(text))


def in_text(text: str) -> Iterator[Link]:
    """Yield each source span once, in order. Reference images use their definition."""
    has_markdown = "![" in text and (
        _IMAGE_DESTINATION.search(text) is not None
        or _DEFINITION.search(text) is not None
    )
    if not has_markdown and "<" not in text:
        return
    code = list(_code(text)) if "`" in text or "~~~" in text else []
    # Hide tags in code without changing offsets or newline positions.
    html_pieces: list[str] = []
    previous = 0
    for start, end in code:
        html_pieces.extend((text[previous:start], text[start:end].replace("<", " ")))
        previous = end
    markup = _Markup("".join([*html_pieces, text[previous:]]) if code else text)
    if not has_markdown:
        yield from sorted(markup.links, key=lambda link: link.start)
        return
    blocked = sorted([*code, *markup.markup])
    blocked_index = 0

    def inside(position: int) -> bool:
        nonlocal blocked_index
        while blocked_index < len(blocked) and blocked[blocked_index][1] <= position:
            blocked_index += 1
        return blocked_index < len(blocked) and blocked[blocked_index][0] <= position

    definitions: dict[str, Link | None] = {}
    for match in _DEFINITION.finditer(text):
        if inside(match.start()) or (span := _destination(text, match.end())) is None:
            continue
        start, end, after = span
        if _DEFINITION_END.match(text, after):
            definitions.setdefault(
                _label(match[1]), _link(text, start, end, markdown=True)
            )

    blocked_index = 0
    stack = array("I")
    seen: set[tuple[int, int]] = set()
    matches = markup.links
    consumed = 0
    for token in _MARKDOWN_TOKEN.finditer(text):
        position = token.start()
        if position < consumed or inside(position):
            continue
        value = token[0]
        if value in ("![", "["):
            stack.append(2 * token.end() + int(value == "!["))
        elif value == "]" and stack:
            start, image = divmod(stack.pop(), 2)
            end = token.end()
            link = None
            if text.startswith("(", end) and (span := _destination(text, end + 1)):
                first, last, after = span
                if closing := _LINK_END.match(text, after):
                    consumed = closing.end()
                    if image:
                        link = _link(text, first, last, markdown=True)
            if image and link is None and end >= consumed and position - start <= 999:
                suffix = _LABEL_SUFFIX.match(text, end)
                label = suffix[1] if suffix and suffix[1] else text[start:position]
                link = definitions.get(_label(label))
                if suffix and link:
                    consumed = suffix.end()
            if link and (link.start, link.end) not in seen:
                matches.append(link)
                seen.add((link.start, link.end))
        elif value == "\n" and text.startswith("\n", token.end()):
            del stack[:]
    yield from sorted(matches, key=lambda link: link.start)


def _fields(data: registry.Payload) -> Iterator[tuple[object, str | int, str, bool]]:
    fields = card.fields_of(data["spec"], data["card"])
    pending: list[tuple[object, str | int, object]] = [
        (fields, key, value)
        for key, value in reversed(list(fields.items()))
        if key not in ("extensions", "character_book", "assets")
    ]
    while pending:
        parent, key, value = pending.pop()
        if isinstance(value, str):
            yield parent, key, value, False
        elif isinstance(value, list):
            items = cast(list[object], value)
            pending.extend(
                (items, index, items[index]) for index in range(len(items) - 1, -1, -1)
            )
        elif isinstance(value, dict):
            mapping = cast(dict[str, object], value)
            pending.extend(
                (mapping, name, mapping[name])
                for name in reversed(mapping)
                if name != "extensions"
            )
    assets = fields.get("assets")
    if isinstance(assets, list):
        for asset in cast(list[object], assets):
            if isinstance(asset, dict):
                mapping = cast(dict[str, object], asset)
                uri = mapping.get("uri")
                if isinstance(uri, str):
                    yield mapping, "uri", uri, True


def _find(text: str, asset: bool) -> Iterator[Link]:
    if asset:
        if (link := _link(text, 0, len(text), entities=False)) and (
            link.url.lower().startswith("https://") or link.reference is not None
        ):
            yield link
    else:
        yield from in_text(text)


def collect(data: registry.Payload) -> tuple[list[str], list[int], int]:
    urls: dict[str, None] = {}
    references: dict[int, None] = {}
    for _, _, text, asset in _fields(data):
        for link in _find(text, asset):
            if (post_id := link.reference) is not None:
                references[post_id] = None
            else:
                urls[link.url] = None
    return list(urls)[:MAX_LINKS], list(references), max(0, len(urls) - MAX_LINKS)


def rewrite(
    data: registry.Payload,
    resolver: Callable[[Link], str | None],
    *,
    include_assets: bool = True,
) -> int:
    """Replace matched image links in card text (and optionally assets) in place."""
    count = 0
    for parent, key, text, asset in _fields(data):
        if asset and not include_assets:
            continue
        parts: list[str] = []
        previous = 0
        for link in _find(text, asset):
            if link.start < previous:
                continue
            replacement = resolver(link)
            if replacement is not None:
                parts.extend((text[previous : link.start], replacement))
                previous = link.end
                count += 1
        if parts:
            value = "".join([*parts, text[previous:]])
            if isinstance(parent, dict):
                cast(dict[object, object], parent)[key] = value
            else:
                assert isinstance(key, int)
                cast(list[object], parent)[key] = value
    return count


def replace(data: registry.Payload, archived: Mapping[str, int]) -> int:
    return rewrite(
        data,
        lambda link: (
            f"lithica:post/{archived[link.url]}" if link.url in archived else None
        ),
    )
