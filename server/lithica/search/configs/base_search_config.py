from collections.abc import Callable

from lithica.search import criteria, tokens
from lithica.search.query import SearchQuery
from lithica.search.typing import SaColumn, SaQuery

Filter = Callable[[SaQuery, criteria.BaseCriterion | None, bool], SaQuery]


class BaseSearchConfig:
    SORT_NONE = tokens.SortToken.SORT_NONE
    SORT_ASC = tokens.SortToken.SORT_ASC
    SORT_DESC = tokens.SortToken.SORT_DESC

    def on_search_query_parsed(self, search_query: SearchQuery) -> None:
        pass

    def create_filter_query(self, _disable_eager_loads: bool) -> SaQuery:
        raise NotImplementedError()

    def create_count_query(self, disable_eager_loads: bool) -> SaQuery:
        raise NotImplementedError()

    def create_around_query(self) -> SaQuery:
        raise NotImplementedError()

    def finalize_query(self, query: SaQuery) -> SaQuery:
        return query

    @property
    def id_column(self) -> SaColumn:
        return None

    @property
    def anonymous_filter(self) -> Filter | None:
        return None

    @property
    def special_filters(self) -> dict[str, Filter]:
        return {}

    @property
    def named_filters(self) -> dict[str, Filter]:
        return {}

    @property
    def sort_columns(self) -> dict[str, tuple[SaColumn, str]]:
        return {}
