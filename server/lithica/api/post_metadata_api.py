"""HTTP endpoints for typed relations and external IDs."""

from typing import Annotated, Any

from fastapi import Depends
from pydantic import Field

from lithica import db, model
from lithica.api import resources
from lithica.api.dependencies import fields_of, read_body, require
from lithica.api.routing import ApiRouter
from lithica.api.schemas import Int, RequestModel, request_body, required
from lithica.func import post_metadata as metadata
from lithica.func import posts

router = ApiRouter(tags=["Posts"])
Viewer = Annotated[model.User, Depends(require("posts:view"))]
TypedEditor = Annotated[model.User, Depends(require("posts:edit:typed_relations"))]
ExternalEditor = Annotated[model.User, Depends(require("posts:edit:external_ids"))]
CheckedFields = Annotated[list[str], Depends(fields_of(posts.PostSerializer))]


class TypedRelationCreate(RequestModel):
    from_id: Annotated[Int, Field(alias="from")] = required()
    to: Int = required()
    type: str = required()
    label: str | None = None


class TypedRelationUpdate(RequestModel):
    label: str | None = required()


class ExternalIdsUpdate(RequestModel):
    external_ids: Annotated[
        list[dict[str, str]],
        Field(
            json_schema_extra={
                "items": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string"},
                        "id": {"type": "string"},
                    },
                    "required": ["host", "id"],
                }
            }
        ),
    ] = required()


@router.get("/post/{post_id}/typed-relations", response_model=resources.TypedRelations)
def get_typed_relations(
    post_id: int, user: Viewer, type: str | None = None, direction: str = "any"
) -> Any:
    """List typed relations, with the other post and its signed file URLs."""
    rows = metadata.list_typed_relations(post_id, type, direction)
    return {"results": metadata.serialize_typed_relations(rows, post_id, user)}


@router.post(
    "/typed-relations",
    response_model=resources.TypedRelation,
    openapi_extra=request_body(TypedRelationCreate),
)
def create_typed_relation(
    user: TypedEditor,
    body: Annotated[TypedRelationCreate, Depends(read_body(TypedRelationCreate))],
) -> Any:
    """Create a typed relation, without changing either post's version or snapshots."""
    row = metadata.create_typed_relation(
        body.require("from_id"),
        body.require("to"),
        body.require("type"),
        body.label,
        user,
    )
    result = metadata.serialize_typed_relations([row], row.from_post_id, user)[0]
    db.session.commit()
    return result


@router.put(
    "/typed-relation/{relation_id}",
    response_model=resources.TypedRelation,
    openapi_extra=request_body(TypedRelationUpdate),
)
def update_typed_relation(
    relation_id: int,
    user: TypedEditor,
    body: Annotated[TypedRelationUpdate, Depends(read_body(TypedRelationUpdate))],
) -> Any:
    """Change only the label of a visible typed relation. Null clears it."""
    row = metadata.get_typed_relation(relation_id)
    row.label = metadata.clean_label(body.require("label"))
    result = metadata.serialize_typed_relations([row], row.from_post_id, user)[0]
    db.session.commit()
    return result


@router.delete("/typed-relation/{relation_id}", response_model=resources.Empty)
def delete_typed_relation(relation_id: int, _user: TypedEditor) -> Any:
    """Delete a visible typed relation."""
    db.session.delete(metadata.get_typed_relation(relation_id))
    db.session.commit()
    return {}


@router.put(
    "/post/{post_id}/external-ids",
    response_model=resources.Post,
    openapi_extra=request_body(ExternalIdsUpdate),
)
def set_external_ids(
    post_id: int,
    user: ExternalEditor,
    fields: CheckedFields,
    body: Annotated[ExternalIdsUpdate, Depends(read_body(ExternalIdsUpdate))],
) -> Any:
    """Replace all external IDs, without changing the post version or snapshots."""
    post = posts.get_post_by_id(post_id)
    metadata.replace_external_ids(
        post, metadata.external_pairs(body.require("external_ids")), user
    )
    result = posts.serialize_post(post, user, fields)
    db.session.commit()
    return result


@router.get("/external-id", response_model=resources.Post)
def get_external_id(user: Viewer, fields: CheckedFields, host: str, id: str) -> Any:
    """Find a visible post by its exact, case-sensitive external ID."""
    return posts.serialize_post(metadata.lookup_external_id(host, id), user, fields)
