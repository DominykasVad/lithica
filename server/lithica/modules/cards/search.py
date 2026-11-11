"""Search current card projections without reading document JSON.

Creator, spec, greetings and linked entry totals come from module tables;
file format remains a fact of the extracted content.
"""

from typing import Any

import sqlalchemy as sa

from lithica import errors, model
from lithica.modules.cards import card as card_format
from lithica.modules.cards.model import Card, CardLorebook, Lorebook
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


def _current(column: Any, factory: Any) -> Filter:
    return search_util.create_subquery_filter(
        model.Post.post_id, Card.post_id, column, factory
    )


_entries = (
    sa.select(sa.func.coalesce(sa.func.sum(Lorebook.entries), 0))
    .select_from(CardLorebook)
    .join(Lorebook, Lorebook.post_id == CardLorebook.lorebook_post_id)
    .where(CardLorebook.card_post_id == Card.post_id)
    .correlate(Card)
    .scalar_subquery()
)


FILTERS: dict[str, Filter] = {
    # card-creator:<pattern>, as the card has it, wildcards allowed
    "card-creator": _current(Card.creator, search_util.create_str_filter),
    # card-spec:v1|v2|v3
    "card-spec": _current(Card.spec, _one_of(_SPECS)),
    # card-format:png|charx
    "card-format": _filter(
        model.PostContent.payload["format"].as_string(), _one_of(_FORMATS)
    ),
    # card-lorebook:yes|no
    "card-lorebook": _current(_entries, _has_any),
    # card-greetings:<number or range>
    "card-greetings": _current(Card.greetings, search_util.create_num_filter),
}
