"""
The search tokens of the cards module. All of them look at the summary
that is stored beside a card (see lithica.modules.cards.card.summary) or at
its kind, never into the card itself, and all of them are written with what
every database has.
"""

from typing import Any

from lithica import errors, model
from lithica.modules.cards import card as card_format
from lithica.search import criteria
from lithica.search.configs import util as search_util
from lithica.search.configs.base_search_config import Filter
from lithica.search.typing import SaColumn, SaQuery

_SPECS = {name: kind for kind, name in card_format.SPEC_NAMES.items()}
_FORMATS = {"png": "png", "charx": "charx"}
_YES_NO = {
    "yes": True,
    "true": True,
    "1": True,
    "no": False,
    "false": False,
    "0": False,
}


def _cards_only(subquery: SaQuery) -> SaQuery:
    return subquery.filter(model.PostContent.kind.in_(card_format.KINDS))


def _one_of(values: dict[str, Any]) -> Any:
    """A text filter whose values are these words and nothing else."""

    def factory(column: SaColumn) -> Filter:
        return search_util.create_str_filter(
            column, lambda value: search_util.enum_transformer(values, value)
        )

    return factory


def _has_any(column: SaColumn) -> Filter:
    """A yes-or-no filter on a count: yes is more than none."""

    def wrapper(
        query: SaQuery, criterion: criteria.BaseCriterion | None, negated: bool
    ) -> SaQuery:
        if not isinstance(criterion, criteria.PlainCriterion):
            raise errors.SearchError("The value must be 'yes' or 'no'.")
        # typed as a text; what it returns is what the table holds
        wanted: Any = search_util.enum_transformer(_YES_NO, criterion.value)
        expression = column > 0 if wanted else column == 0
        return query.filter(~expression if negated else expression)

    return wrapper


def _filter(column: Any, factory: Any) -> Filter:
    return search_util.create_subquery_filter(
        model.Post.post_id,
        model.PostContent.post_id,
        column,
        factory,
        _cards_only,
    )


def _summary(name: str) -> Any:
    return model.PostContent.payload[("summary", name)]


FILTERS: dict[str, Filter] = {
    # card-creator:<pattern>, as the card has it, wildcards allowed
    "card-creator": _filter(
        _summary("creator").as_string(), search_util.create_str_filter
    ),
    # card-spec:v1|v2|v3
    "card-spec": _filter(model.PostContent.kind, _one_of(_SPECS)),
    # card-format:png|charx
    "card-format": _filter(
        model.PostContent.payload["format"].as_string(), _one_of(_FORMATS)
    ),
    # card-lorebook:yes|no
    "card-lorebook": _filter(_summary("lorebookEntries").as_integer(), _has_any),
    # card-greetings:<number or range>
    "card-greetings": _filter(
        _summary("greetings").as_integer(), search_util.create_num_filter
    ),
}
