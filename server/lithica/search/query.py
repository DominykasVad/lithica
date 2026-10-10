from lithica.search import tokens


class SearchQuery:
    def __init__(self) -> None:
        self.anonymous_tokens: list[tokens.AnonymousToken] = []
        self.named_tokens: list[tokens.NamedToken] = []
        self.special_tokens: list[tokens.SpecialToken] = []
        self.sort_tokens: list[tokens.SortToken] = []

    def __hash__(self) -> int:
        return hash(
            (
                tuple(self.anonymous_tokens),
                tuple(self.named_tokens),
                tuple(self.special_tokens),
                tuple(self.sort_tokens),
            )
        )
