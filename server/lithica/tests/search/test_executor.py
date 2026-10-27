import pytest

from lithica import db, search


def _query_key(executor, query_text, offset, limit, user=None):
    """
    Identity of a search: the parsed query as the config sees it, plus the
    page. Two searches with the same key ask the database the same thing.
    """
    search_query = executor.parser.parse(query_text)
    executor.config.on_search_query_parsed(search_query, user)
    return (hash(search_query), offset, limit)


def test_results_are_not_cached(post_factory):
    executor = search.Executor(search.configs.PostSearchConfig())
    db.session.add(post_factory())
    db.session.flush()
    assert executor.execute("", 0, 10)[0] == 1
    db.session.add(post_factory())
    db.session.flush()
    # no purge in between: a search always reads the database
    count, posts = executor.execute("", 0, 10)
    assert count == 2
    assert len(posts) == 2


def test_equivalent_queries_are_the_same_search():
    config = search.configs.PostSearchConfig()
    executor = search.Executor(config)
    hashes = []
    hashes.append(_query_key(executor, "safety:safe test", 1, 10))
    hashes.append(_query_key(executor, "safety:safe  test", 1, 10))
    hashes.append(_query_key(executor, "safety:safe test ", 1, 10))
    hashes.append(_query_key(executor, " safety:safe test", 1, 10))
    hashes.append(_query_key(executor, " SAFETY:safe test", 1, 10))
    hashes.append(_query_key(executor, "test safety:safe", 1, 10))
    assert len(hashes) == 6
    assert len(set(hashes)) == 1


def test_non_equivalent_queries_are_different_searches():
    config = search.configs.PostSearchConfig()
    executor = search.Executor(config)
    hashes = []
    args = [
        ("", 1, 10),
        ("creation-time:2016", 1, 10),
        ("creation-time:2015", 1, 10),
        ("creation-time:2016-01", 1, 10),
        ("creation-time:2016-02", 1, 10),
        ("creation-time:2016-01-01", 1, 10),
        ("creation-time:2016-01-02", 1, 10),
        ("tag-count:1,3", 1, 10),
        ("tag-count:1,2", 1, 10),
        ("tag-count:1", 1, 10),
        ("tag-count:1..3", 1, 10),
        ("tag-count:1..4", 1, 10),
        ("tag-count:2..3", 1, 10),
        ("tag-count:1..", 1, 10),
        ("tag-count:2..", 1, 10),
        ("tag-count:..3", 1, 10),
        ("tag-count:..4", 1, 10),
        ("-tag-count:1..3", 1, 10),
        ("-tag-count:1..4", 1, 10),
        ("-tag-count:2..3", 1, 10),
        ("-tag-count:1..", 1, 10),
        ("-tag-count:2..", 1, 10),
        ("-tag-count:..3", 1, 10),
        ("-tag-count:..4", 1, 10),
        ("safety:safe", 1, 10),
        ("safety:safe", 1, 20),
        ("safety:safe", 2, 10),
        ("safety:sketchy", 1, 10),
        ("safety:safe test", 1, 10),
        ("-safety:safe", 1, 10),
        ("-safety:safe", 1, 20),
        ("-safety:safe", 2, 10),
        ("-safety:sketchy", 1, 10),
        ("-safety:safe test", 1, 10),
        ("safety:safe -test", 1, 10),
        ("-test", 1, 10),
    ]
    for arg in args:
        hashes.append(_query_key(executor, *arg))
    assert len(hashes) == len(args)
    assert len(set(hashes)) == len(args)


@pytest.mark.parametrize(
    "input",
    [
        "special:fav",
        "special:liked",
        "special:disliked",
        "-special:fav",
        "-special:liked",
        "-special:disliked",
    ],
)
def test_auth_dependent_queries_differ_by_user(user_factory, input):
    config = search.configs.PostSearchConfig()
    executor = search.Executor(config)
    hashes = []

    first, second = user_factory(), user_factory()
    hashes.append(_query_key(executor, input, 1, 1, first))
    assert len(set(hashes)) == 1

    hashes.append(_query_key(executor, input, 1, 1, second))
    assert len(set(hashes)) == 2

    hashes.append(_query_key(executor, input, 1, 1, second))
    assert len(set(hashes)) == 2
