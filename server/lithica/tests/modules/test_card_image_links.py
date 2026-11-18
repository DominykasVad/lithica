from time import monotonic

from lithica.modules.cards import card, image_links
from lithica.tests.modules import cards

TEXT = """![an [alt]](https://images.test/inline?a=1&amp;b=2 "title")
![ref-style][same] ![same][] ![same]
[same]: <https://images.test/ref> 'title'
[unused]: https://images.test/unused
[ordinary](https://images.test/ordinary)
<a href="https://images.test/href">Link</a> https://images.test/bare
<img alt="label" src="  https://images.test/img  "
 srcset="https://images.test/small 1x, https://images.test/large 2x">
<source srcset='https://images.test/narrow 400w, https://images.test/wide 800w'>
<div style="background: url('https://images.test/style')"></div>
<style>p { background: url( https://images.test/css ) }</style>
![direct](lithica:post/19)
<img src='lithica:post/29'>
![ignore](ftp://images.test/ftp) <img src="//images.test/relative">
"""

EXPECTED = [
    "https://images.test/inline?a=1&b=2",
    "https://images.test/ref",
    "https://images.test/img",
    "https://images.test/small",
    "https://images.test/large",
    "https://images.test/narrow",
    "https://images.test/wide",
    "https://images.test/style",
    "https://images.test/css",
]


def test_image_contexts_keep_source_spelling_when_replaced() -> None:
    data = {
        "spec": card.KIND_V3,
        "card": cards.v3_card(first_mes=TEXT),
    }
    assert image_links.collect(data) == (EXPECTED, [19, 29], 0)
    ids = {url: 51 + i for i, url in enumerate(EXPECTED)}
    assert image_links.replace(data, ids) == len(ids)
    expected = TEXT
    for url, id_ in ids.items():
        expected = expected.replace(url.replace("&", "&amp;"), f"lithica:post/{id_}")
    assert data["card"]["data"]["first_mes"] == expected
    assert image_links.collect(data) == ([], [*ids.values(), 19, 29], 0)


def test_lists_translations_assets_and_limits() -> None:
    target = "https://images.test/"
    long_url = target + "x" * 2048
    data = {
        "spec": card.KIND_V3,
        "card": cards.v3_card(
            first_mes=f"![too long]({long_url})",
            alternate_greetings=[f"![alternate]({target}alternate)"],
            group_only_greetings=[f'<img src="{target}group">'],
            creator_notes_multilingual={"en": f"![note]({target}note)"},
            extensions={"nested": [f"![ignored]({target}extension)"]},
            character_book={"entries": [{"content": f"![book]({target}book)"}]},
            assets=[
                {"uri": target + "asset", "name": f"![name]({target}name)"},
                {"uri": "http://images.test/not-https"},
            ],
        ),
    }
    urls, references, dropped = image_links.collect(data)
    assert urls == [target + name for name in ("alternate", "group", "note", "asset")]
    assert not references and not dropped
    data["card"]["data"]["first_mes"] = " ".join(
        f"![a]({target}{i})" for i in range(503)
    )
    assert image_links.collect(data) == ([target + str(i) for i in range(500)], [], 7)


def test_maximum_text_with_nested_near_matches_is_bounded() -> None:
    text = ("![![[](" * (card.MAX_CARD_SIZE // 8 + 1))[: card.MAX_CARD_SIZE]
    start = monotonic()
    assert list(image_links.in_text(text)) == []
    assert monotonic() - start < 8


def test_entities_in_css_quotes_and_srcset_descriptors_preserve_source() -> None:
    text = (
        '<img srcset="https://images.test/a&#32;1x, https://images.test/b 2x" '
        'style="background: url(&quot; https://images.test/c?a=1&amp;b=2 &quot;)">'
        "<style>/* url(https://images.test/comment) */</style>"
    )
    data = {"spec": card.KIND_V1, "card": {"description": text}}
    urls, _, _ = image_links.collect(data)
    assert urls == [
        "https://images.test/a",
        "https://images.test/b",
        "https://images.test/c?a=1&b=2",
    ]
    assert image_links.replace(data, dict.fromkeys(urls, 4)) == 3
    assert data["card"]["description"] == (
        '<img srcset="lithica:post/4&#32;1x, lithica:post/4 2x" '
        'style="background: url(&quot; lithica:post/4 &quot;)">'
        "<style>/* url(https://images.test/comment) */</style>"
    )


def test_code_and_comments_are_not_image_contexts() -> None:
    text = """`<img src="https://images.test/code">`
<!-- <img src="https://images.test/comment"> -->
```html
<img src="https://images.test/fenced">
```
`![code](https://images.test/markdown)`
<img src="https://images.test/actual">"""
    assert [link.url for link in image_links.in_text(text)] == [
        "https://images.test/actual"
    ]
