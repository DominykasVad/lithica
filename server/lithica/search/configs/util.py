from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica import db, errors
from lithica.func import util
from lithica.search import criteria
from lithica.search.configs.base_search_config import Filter
from lithica.search.typing import SaColumn, SaQuery

Number = int | float
WILDCARD = "(--wildcard--)"  # something unlikely to be used by the users


def unescape(text: str, make_wildcards_special: bool = False) -> str:
    output = ""
    i = 0
    while i < len(text):
        if text[i] == "\\":
            try:
                char = text[i + 1]
                i += 1
            except IndexError as ex:
                raise errors.SearchError(
                    "Unterminated escape sequence (did you forget to escape "
                    "the ending backslash?)"
                ) from ex
            if char not in "*\\:-.,":
                raise errors.SearchError(
                    "Unknown escape sequence (did you forget to escape the backslash?)"
                )
        elif text[i] == "*" and make_wildcards_special:
            char = WILDCARD
        else:
            char = text[i]
        output += char
        i += 1
    return output


def wildcard_transformer(value: str) -> str:
    return (
        unescape(value, make_wildcards_special=True)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace(WILDCARD, "%")
    )


def enum_transformer(available_values: dict[str, Any], value: str) -> str:
    try:
        return available_values[unescape(value.lower())]
    except KeyError as ex:
        raise errors.SearchError(
            "Invalid value: %r. Possible values: %r."
            % (value, list(sorted(available_values.keys())))
        ) from ex


def integer_transformer(value: str) -> int:
    return int(unescape(value))


def float_transformer(value: str) -> float:
    for sep in list("/:"):
        if sep in value:
            a, b = value.split(sep, 1)
            return float(unescape(a)) / float(unescape(b))
    return float(unescape(value))


def apply_num_criterion_to_column(
    column: Any,
    criterion: criteria.BaseCriterion,
    transformer: Callable[[str], Number] = integer_transformer,
) -> SaQuery:
    try:
        if isinstance(criterion, criteria.PlainCriterion):
            expr = column == transformer(criterion.value)
        elif isinstance(criterion, criteria.ArrayCriterion):
            expr = column.in_(transformer(value) for value in criterion.values)
        elif isinstance(criterion, criteria.RangedCriterion):
            assert criterion.min_value or criterion.max_value
            if criterion.min_value and criterion.max_value:
                expr = column.between(
                    transformer(criterion.min_value),
                    transformer(criterion.max_value),
                )
            elif criterion.min_value:
                expr = column >= transformer(criterion.min_value)
            elif criterion.max_value:
                expr = column <= transformer(criterion.max_value)
        else:
            raise AssertionError()
    except ValueError as ex:
        raise errors.SearchError(
            "Criterion value %r must be a number." % (criterion,)
        ) from ex
    return expr


def create_num_filter(
    column: Any, transformer: Callable[[str], Number] = integer_transformer
) -> SaQuery:
    def wrapper(
        query: SaQuery,
        criterion: criteria.BaseCriterion | None,
        negated: bool,
    ) -> SaQuery:
        assert criterion
        expr = apply_num_criterion_to_column(column, criterion, transformer)
        if negated:
            expr = ~expr
        return query.filter(expr)

    return wrapper


def _like_ignoring_case(column: SaColumn, pattern: str) -> Any:
    """
    Case-insensitive LIKE that every database understands, unlike ILIKE.
    The escape character is named because only some databases default to
    the backslash that wildcard_transformer escapes with.
    """
    return sa.func.lower(column).like(sa.func.lower(pattern), escape="\\")


def apply_str_criterion_to_column(
    column: SaColumn,
    criterion: criteria.BaseCriterion,
    transformer: Callable[[str], str] = wildcard_transformer,
) -> SaQuery:
    if isinstance(criterion, criteria.PlainCriterion):
        expr = _like_ignoring_case(column, transformer(criterion.value))
    elif isinstance(criterion, criteria.ArrayCriterion):
        expr = sa.sql.false()
        for value in criterion.values:
            expr = expr | _like_ignoring_case(column, transformer(value))
    elif isinstance(criterion, criteria.RangedCriterion):
        raise errors.SearchError(
            "Ranged criterion is invalid in this context. "
            "Did you forget to escape the dots?"
        )
    else:
        raise AssertionError()
    return expr


def create_str_filter(
    column: SaColumn, transformer: Callable[[str], str] = wildcard_transformer
) -> Filter:
    def wrapper(
        query: SaQuery,
        criterion: criteria.BaseCriterion | None,
        negated: bool,
    ) -> SaQuery:
        assert criterion
        expr = apply_str_criterion_to_column(column, criterion, transformer)
        if negated:
            expr = ~expr
        return query.filter(expr)

    return wrapper


def apply_date_criterion_to_column(
    column: SaQuery, criterion: criteria.BaseCriterion
) -> SaQuery:
    if isinstance(criterion, criteria.PlainCriterion):
        min_date, max_date = util.parse_time_range(criterion.value)
        expr = column.between(min_date, max_date)
    elif isinstance(criterion, criteria.ArrayCriterion):
        expr = sa.sql.false()
        for value in criterion.values:
            min_date, max_date = util.parse_time_range(value)
            expr = expr | column.between(min_date, max_date)
    elif isinstance(criterion, criteria.RangedCriterion):
        assert criterion.min_value or criterion.max_value
        if criterion.min_value and criterion.max_value:
            min_date = util.parse_time_range(criterion.min_value)[0]
            max_date = util.parse_time_range(criterion.max_value)[1]
            expr = column.between(min_date, max_date)
        elif criterion.min_value:
            min_date = util.parse_time_range(criterion.min_value)[0]
            expr = column >= min_date
        elif criterion.max_value:
            max_date = util.parse_time_range(criterion.max_value)[1]
            expr = column <= max_date
    else:
        raise AssertionError()
    return expr


def create_date_filter(column: SaColumn) -> Filter:
    def wrapper(
        query: SaQuery,
        criterion: criteria.BaseCriterion | None,
        negated: bool,
    ) -> SaQuery:
        assert criterion
        expr = apply_date_criterion_to_column(column, criterion)
        if negated:
            expr = ~expr
        return query.filter(expr)

    return wrapper


def create_subquery_filter(
    left_id_column: SaColumn,
    right_id_column: SaColumn,
    filter_column: SaColumn,
    filter_factory: SaColumn,
    subquery_decorator: Callable[[SaQuery], SaQuery] | None = None,
) -> Filter:
    filter_func = filter_factory(filter_column)

    def wrapper(
        query: SaQuery,
        criterion: criteria.BaseCriterion | None,
        negated: bool,
    ) -> SaQuery:
        assert criterion
        subquery = db.session.query(right_id_column.label("foreign_id"))
        if subquery_decorator:
            subquery = subquery_decorator(subquery)
        subquery = subquery.options(sa_orm.lazyload("*"))
        subquery = filter_func(subquery, criterion, False)
        subquery = subquery.subquery("t")
        expression = left_id_column.in_(sa.select(subquery.c.foreign_id))
        if negated:
            expression = ~expression
        return query.filter(expression)

    return wrapper
