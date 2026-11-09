from lithica.model.base import Base
from lithica.model.comment import Comment, CommentScore
from lithica.model.pool import Pool, PoolName, PoolPost
from lithica.model.pool_category import PoolCategory
from lithica.model.post import (
    Post,
    PostContent,
    PostExternalId,
    PostFavorite,
    PostFeature,
    PostNote,
    PostRelation,
    PostScore,
    PostSignature,
    PostSignatureWord,
    PostTag,
    PostTypedRelation,
)
from lithica.model.share_link import ShareLink
from lithica.model.snapshot import Snapshot
from lithica.model.tag import Tag, TagImplication, TagName, TagSuggestion
from lithica.model.tag_category import TagCategory
from lithica.model.user import PasswordResetToken, User, UserToken

from lithica.model import util  # isort: skip  (needs the models above)
from lithica.model.post import add_relation_count  # isort: skip

# needs every model above
add_relation_count()
