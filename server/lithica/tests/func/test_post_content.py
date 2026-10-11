import io
import logging

import pytest

from lithica import model, registry
from lithica.func import content as content_module
from lithica.func import post_content

PNG = "image/png"


def _module(name="alpha", kinds=("alpha_v1",), extractors=()):
    return registry.Module(
        name=name,
        content_kinds=[registry.ContentKind(kind) for kind in kinds],
        extractors=extractors,
    )


def _extractor(function, mime_types=(PNG,)):
    return registry.Extractor(frozenset(mime_types), function)


def _found(kind="alpha_v1", **payload):
    return registry.ExtractedContent(kind, payload)


def test_no_extractor_finds_nothing():
    extraction = post_content.extract(PNG, b"content")
    assert extraction.contents == []
    assert extraction.failed_kinds == set()


def test_extractor_is_given_the_mime_type_and_the_file():
    seen = []

    def extract(mime_type, handle):
        seen.append((mime_type, handle.read()))
        return [_found(text="hello"), _found(text="again")]

    registry.use([_module(extractors=[_extractor(extract)])])
    extraction = post_content.extract(PNG, b"the bytes")
    assert seen == [(PNG, b"the bytes")]
    assert extraction.contents == [_found(text="hello"), _found(text="again")]
    assert extraction.failed_kinds == set()


def test_extractor_reads_a_file_backed_content(tmp_path):
    path = tmp_path / "upload"
    path.write_bytes(b"on disk")
    handles = []

    def extract(_mime_type, handle):
        handles.append(handle)
        # a real file: it can be handed to a library that wants one
        assert not isinstance(handle, io.BytesIO)
        return [_found(text=handle.read().decode())]

    registry.use([_module(extractors=[_extractor(extract)])])
    extraction = post_content.extract(PNG, content_module.Content(str(path)))
    assert extraction.contents == [_found(text="on disk")]
    assert handles[0].closed


def test_extractors_are_keyed_by_mime_type():
    registry.use(
        [
            _module(
                extractors=[
                    _extractor(lambda m, f: [_found(source="png")], [PNG]),
                    _extractor(
                        lambda m, f: [_found(source="pictures")],
                        [PNG, "image/webp"],
                    ),
                    _extractor(lambda m, f: [_found(source="video")], ["video/mp4"]),
                ]
            )
        ]
    )

    def sources(mime_type):
        extraction = post_content.extract(mime_type, b"")
        return [content.payload["source"] for content in extraction.contents]

    assert sources(PNG) == ["png", "pictures"]
    assert sources("image/webp") == ["pictures"]
    assert sources("video/mp4") == ["video"]
    assert sources("image/gif") == []


def test_every_extractor_reads_from_the_start():
    def extract(_mime_type, handle):
        return [_found(text=handle.read().decode())]

    registry.use([_module(extractors=[_extractor(extract), _extractor(extract)])])
    extraction = post_content.extract(PNG, b"all of it")
    assert [content.payload["text"] for content in extraction.contents] == [
        "all of it",
        "all of it",
    ]


def test_generator_extractor():
    def extract(_mime_type, _handle):
        yield _found(n=1)
        yield _found(n=2)

    registry.use([_module(extractors=[_extractor(extract)])])
    assert post_content.extract(PNG, b"").contents == [_found(n=1), _found(n=2)]


def test_failing_extractor_does_not_stop_the_others(caplog):
    def broken(_mime_type, _handle):
        raise ValueError("cannot parse this")

    registry.use(
        [
            _module("broken", ["broken_v1", "broken_v2"], [_extractor(broken)]),
            _module(
                "working",
                ["working_v1"],
                [_extractor(lambda m, f: [_found("working_v1", ok=True)])],
            ),
        ]
    )
    with caplog.at_level(logging.ERROR):
        extraction = post_content.extract(PNG, b"")
    assert extraction.contents == [_found("working_v1", ok=True)]
    assert extraction.failed_kinds == {"broken_v1", "broken_v2"}
    assert "module 'broken' failed on a image/png file" in caplog.text
    assert "cannot parse this" in caplog.text


def test_extractor_failing_half_way_contributes_nothing():
    def extract(_mime_type, _handle):
        yield _found(n=1)
        raise RuntimeError("truncated file")

    registry.use([_module(extractors=[_extractor(extract)])])
    extraction = post_content.extract(PNG, b"")
    assert extraction.contents == []
    assert extraction.failed_kinds == {"alpha_v1"}


def test_exit_of_the_process_is_not_swallowed():
    def extract(_mime_type, _handle):
        raise KeyboardInterrupt()

    registry.use([_module(extractors=[_extractor(extract)])])
    with pytest.raises(KeyboardInterrupt):
        post_content.extract(PNG, b"")


SECRET = "the-secret-in-the-file"


@pytest.mark.parametrize(
    "results,problem",
    [
        ([("alpha_v1", {"text": SECRET})], "returned tuple"),
        ([None], "returned NoneType"),
        ([_found("beta_v1", text=SECRET)], "kind 'beta_v1', which module 'alpha'"),
        ([registry.ExtractedContent("alpha_v1", [SECRET])], "not an object"),  # type: ignore[arg-type]  (the wrong type is the point)
        ([registry.ExtractedContent("alpha_v1", None)], "not an object"),  # type: ignore[arg-type]  (the wrong type is the point)
        ([_found(data=SECRET.encode())], "not JSON"),
        ([_found(when=object())], "not JSON"),
        ([_found(number=float("nan"))], "not JSON"),
        ([_found(number=float("inf"))], "not JSON"),
        ([_found(text=SECRET + "\ud800")], "not JSON"),
        ([_found(text=SECRET + "\x00")], "NUL character"),
        ([_found(**{"key\x00": SECRET})], "NUL character"),
        ([_found(nested=[{"deep": [SECRET, "a\x00b"]}])], "NUL character"),
        (
            [_found(text="x" * post_content.MAX_PAYLOAD_SIZE)],
            "bytes (the limit is %d)" % post_content.MAX_PAYLOAD_SIZE,
        ),
        (
            [_found(n=n) for n in range(post_content.MAX_RESULTS + 1)],
            "more than %d results" % post_content.MAX_RESULTS,
        ),
    ],
)
def test_result_outside_the_contract_is_dropped(caplog, results, problem):
    registry.use(
        [
            _module(extractors=[_extractor(lambda m, f: results)]),
            _module("beta", ["beta_v1"]),
        ]
    )
    with caplog.at_level(logging.ERROR):
        extraction = post_content.extract(PNG, b"")
    assert extraction.contents == []
    assert extraction.failed_kinds == {"alpha_v1"}
    assert "An extractor of module 'alpha'" in caplog.text
    assert problem in caplog.text
    # what was in the file stays out of the log
    assert SECRET not in caplog.text


def test_one_bad_result_drops_all_results_of_that_extractor():
    registry.use(
        [
            _module(
                extractors=[
                    _extractor(lambda m, f: [_found(n=1), _found(text="\x00")]),
                    _extractor(lambda m, f: [_found(n=2)]),
                ]
            )
        ]
    )
    extraction = post_content.extract(PNG, b"")
    assert extraction.contents == [_found(n=2)]
    assert extraction.failed_kinds == {"alpha_v1"}


def test_text_that_only_looks_like_an_escape_is_kept():
    payload = {"text": "\\u0000 and \\ud800 are six characters each"}
    registry.use([_module(extractors=[_extractor(lambda m, f: [_found(**payload)])])])
    assert post_content.extract(PNG, b"").contents == [_found(**payload)]


def test_largest_payload_and_most_results_are_kept():
    filler = "x" * (post_content.MAX_PAYLOAD_SIZE - len('{"text": ""}'))
    results = [_found(text=filler)] + [
        _found(n=n) for n in range(post_content.MAX_RESULTS - 1)
    ]
    registry.use([_module(extractors=[_extractor(lambda m, f: results)])])
    extraction = post_content.extract(PNG, b"")
    assert len(extraction.contents) == post_content.MAX_RESULTS
    assert extraction.failed_kinds == set()


def test_payload_is_stored_as_json_has_it():
    payload = {1: "number key", "tuple": (1, 2), "nested": {"ż": [None, True, 1.5]}}
    original = registry.ExtractedContent("alpha_v1", payload)  # type: ignore[arg-type]  (a key that is not a string is the point)
    registry.use([_module(extractors=[_extractor(lambda m, f: [original])])])
    (found,) = post_content.extract(PNG, b"").contents
    assert found.payload == {
        "1": "number key",
        "tuple": [1, 2],
        "nested": {"ż": [None, True, 1.5]},
    }
    # a copy: what the module does with its object later changes nothing
    payload["nested"]["ż"].append("later")
    assert found.payload["nested"]["ż"] == [None, True, 1.5]


def test_limiting_the_extraction_to_some_kinds():
    calls = []

    def extractor(name, *kinds):
        def extract(_mime_type, _handle):
            calls.append(name)
            return [_found(kind, by=name) for kind in kinds]

        return _extractor(extract)

    def broken(_mime_type, _handle):
        calls.append("broken")
        raise ValueError()

    registry.use(
        [
            _module("one", ["one_a", "one_b"], [extractor("one", "one_a", "one_b")]),
            _module("two", ["two_a"], [extractor("two", "two_a")]),
            _module("three", ["three_a", "three_b"], [_extractor(broken)]),
        ]
    )

    extraction = post_content.extract(PNG, b"", kinds=["one_b"])
    assert calls == ["one"]
    assert extraction.contents == [_found("one_b", by="one")]
    assert extraction.failed_kinds == set()

    calls.clear()
    extraction = post_content.extract(PNG, b"", kinds=["two_a", "three_a"])
    assert calls == ["two", "broken"]
    assert extraction.contents == [_found("two_a", by="two")]
    # only what was asked for is reported as failed
    assert extraction.failed_kinds == {"three_a"}

    calls.clear()
    assert post_content.extract(PNG, b"", kinds=["nobody_has_this"]).contents == []
    assert calls == []


def _post_with(*contents):
    post = model.Post()
    post.contents = [
        model.PostContent(kind=content.kind, payload=content.payload)
        for content in contents
    ]
    return post


@pytest.fixture
def tag_rule(config_injector):
    config_injector({"tag_name_regex": r"^\S+$"})


def test_auto_tags_of_no_module(tag_rule):
    assert post_content.get_auto_tags(_post_with(_found(text="x"))) == []


def test_auto_tag_hook_sees_the_content_of_its_own_kinds(tag_rule):
    seen = {}

    def tagger(name):
        def auto_tag(contents):
            seen[name] = list(contents)
            return {name: ["by_" + name]}

        return auto_tag

    registry.use(
        [
            registry.Module(
                name="one",
                content_kinds=[registry.ContentKind("one_a")],
                auto_tag=tagger("one"),
            ),
            registry.Module(
                name="two",
                content_kinds=[
                    registry.ContentKind("two_a"),
                    registry.ContentKind("two_b"),
                ],
                auto_tag=tagger("two"),
            ),
            registry.Module(
                name="three",
                content_kinds=[registry.ContentKind("three_a")],
                auto_tag=tagger("three"),
            ),
        ]
    )
    post = _post_with(
        _found("one_a", n=1),
        _found("two_b", n=2),
        _found("two_a", n=3),
        _found("left_by_a_module_that_is_gone", n=4),
    )
    assert post_content.get_auto_tags(post) == [("one", "by_one"), ("two", "by_two")]
    assert seen == {
        "one": [_found("one_a", n=1)],
        "two": [_found("two_b", n=2), _found("two_a", n=3)],
        # "three" found nothing in the file and is not asked
    }


def _tagging_module(auto_tag, name="alpha"):
    return registry.Module(
        name=name,
        content_kinds=[registry.ContentKind(name + "_v1")],
        auto_tag=auto_tag,
    )


def test_auto_tags_keep_their_order_and_come_once(tag_rule):
    registry.use(
        [
            _tagging_module(
                lambda contents: {"meta": ["b", "a", "B"], "other": ["c", "a"]}
            ),
            _tagging_module(lambda contents: {"third": ["C", "d"]}, "beta"),
        ]
    )
    post = _post_with(_found("alpha_v1"), _found("beta_v1"))
    assert post_content.get_auto_tags(post) == [
        ("meta", "b"),
        ("meta", "a"),
        ("other", "c"),
        ("third", "d"),
    ]


def test_auto_tag_names_the_site_refuses_are_left_out(config_injector):
    config_injector({"tag_name_regex": "^[a-z_]+$"})
    names = ["fine", "has space", "", "UPPER", "also_fine", "x" * 1000, ".", "a\nb"]
    registry.use([_tagging_module(lambda contents: {"meta": names})])
    assert post_content.get_auto_tags(_post_with(_found())) == [
        ("meta", "fine"),
        ("meta", "also_fine"),
    ]


def test_failing_auto_tag_hook_does_not_stop_the_others(tag_rule, caplog):
    def broken(_contents):
        raise KeyError("prompt")

    registry.use(
        [
            _tagging_module(broken),
            _tagging_module(lambda contents: {"meta": ["kept"]}, "beta"),
        ]
    )
    with caplog.at_level(logging.ERROR):
        found = post_content.get_auto_tags(
            _post_with(_found("alpha_v1"), _found("beta_v1"))
        )
    assert found == [("meta", "kept")]
    assert "The auto-tag hook of module 'alpha' failed" in caplog.text


@pytest.mark.parametrize(
    "result,problem",
    [
        (None, "NoneType"),
        ([SECRET], "returned list"),
        ({1: [SECRET]}, "category that is not a string"),
        ({"meta": SECRET}, "tags that are not a list"),
        ({"meta": None}, "tags that are not a list"),
        ({"meta": [SECRET, 1]}, "tag that is not a string"),
        (
            {"meta": ["tag%d" % n for n in range(post_content.MAX_AUTO_TAGS + 1)]},
            "more than %d tags" % post_content.MAX_AUTO_TAGS,
        ),
    ],
)
def test_auto_tags_outside_the_contract_are_dropped(tag_rule, caplog, result, problem):
    registry.use([_tagging_module(lambda contents: result)])
    with caplog.at_level(logging.ERROR):
        assert post_content.get_auto_tags(_post_with(_found())) == []
    assert "The auto-tag hook of module 'alpha' returned" in caplog.text
    assert problem in caplog.text
    assert SECRET not in caplog.text


def test_most_auto_tags_a_module_may_give(tag_rule):
    names = ["tag%d" % n for n in range(post_content.MAX_AUTO_TAGS)]
    registry.use([_tagging_module(lambda contents: {"meta": tuple(names)})])
    assert len(post_content.get_auto_tags(_post_with(_found()))) == len(names)
