# Lithica API

This document explains how the API works: authentication, uploads, errors,
field selection, versioning, what the resources mean and how to search.

The reference of every endpoint, with its parameters and responses, is the
OpenAPI document [`openapi.json`](openapi.json). It is generated from the
server's code and kept in step with it by CI. A running server can show it
as interactive documentation at `docs` (Swagger UI) and `redoc`, next to the
API itself, when `api_docs` is enabled in the server's config; the
development image enables it.

Depending on the deployment, the API's URLs are relative to some base path;
with the client image in front, that is `/api/`.

# Table of contents

1. [General rules](#general-rules)

   - [Authentication](#authentication)
   - [User token authentication](#user-token-authentication)
   - [Basic requests](#basic-requests)
   - [File uploads](#file-uploads)
   - [Error handling](#error-handling)
   - [Field selecting](#field-selecting)
   - [Versioning](#versioning)
   - [Modules](#modules)
   - [Webhooks](#webhooks)
2. [Resources](#resources)

   - [User](#user)
   - [Micro user](#micro-user)
   - [User token](#user-token)
   - [Tag category](#tag-category)
   - [Tag](#tag)
   - [Micro tag](#micro-tag)
   - [Post](#post)
   - [Extracted content](#extracted-content)
   - [Micro post](#micro-post)
   - [Note](#note)
   - [Pool category](#pool-category)
   - [Pool](#pool)
   - [Micro pool](#micro-pool)
   - [Comment](#comment)
   - [Snapshot](#snapshot)
   - [Unpaged search result](#unpaged-search-result)
   - [Paged search result](#paged-search-result)
   - [Image search result](#image-search-result)
3. [Search](#search)

   - [Tag search](#tag-search)
   - [Post search](#post-search)
   - [Pool search](#pool-search)
   - [Comment search](#comment-search)
   - [User search](#user-search)
   - [Snapshot search](#snapshot-search)

# General rules

## Authentication

Authentication is achieved by means of [basic HTTP
auth](https://en.wikipedia.org/wiki/Basic_access_authentication) or through the
use of [user token authentication](#user-token-authentication). For this
reason, it is recommended to connect through HTTPS. There are no sessions, so
every privileged request must be authenticated. Available privileges depend on
the user's rank. The way how rank translates to privileges is defined in the
server's configuration.

It is recommended to add `?bump-login` GET parameter to the first request in a
client "session" (where the definition of a session is up to the client), so
that the user's last login time is kept up to date.

## User token authentication

User token authentication works similarly to [basic HTTP
auth](https://en.wikipedia.org/wiki/Basic_access_authentication). Because it
operates similarly to ***basic HTTP auth*** it is still recommended to connect
through HTTPS. The authorization header uses the type of `Token` and the
username and token are encoded as Base64 and sent as the second parameter.

Example header for user1:token-is-more-secure
```
Authorization: Token dXNlcjE6dG9rZW4taXMtbW9yZS1zZWN1cmU=
```

The benefit of token authentication is that beyond the initial login to acquire
the first token, there is no need to transmit the user password in plaintext
via basic auth. Additionally tokens can be revoked at anytime allowing a
cleaner interface for isolating clients from user credentials.

## Basic requests

Every request must use `Content-Type: application/json` and `Accept:
application/json`. An exception to this rule are requests that upload files.

## File uploads

Requests that upload files must use `multipart/form-data` encoding. Any request
that bundles user files, must send the request data (which is JSON) as an
additional file with the special name of `metadata` (whereas the actual files
must have names specific to the API that is being used.)

The server accepts requests up to the size set as `max_upload_size` in its
config (1 GiB unless changed). A larger request is refused with status 413
and an error named `RequestTooLargeError`.

Alternatively, the server can download the files from the Internet on client's
behalf. In that case, the request doesn't need to be specially encoded in any
way. The files, however, should be passed as regular fields appended with a
`Url` suffix. For example, to use `http://example.com/file.jpg` in an API that
accepts a file named `content`, the client should pass
`{"contentUrl":"http://example.com/file.jpg"}` as a part of the JSON message
body. When creating or updating post content using this method, the server can
also be configured to employ [yt-dlp](https://github.com/yt-dlp/yt-dlp) to
download content from popular sites such as youtube, gfycat, etc. Access to
yt-dlp can be configured with the `'uploads:use_downloader'` permission

Only `http` and `https` URLs are downloaded; anything else is a validation
error. The server also refuses to download from addresses that are not public
(loopback, private networks, link-local and the like), at the first request
and at every redirect, unless `allow_private_downloads` is set in the server
config. A refused address, a failed connection and a timeout all give the
same error, so that the answer does not describe the server's network.

Finally, in some cases the user might want to reuse one file between the
requests to save the bandwidth (for example, reverse search + consecutive
upload). In this case one should use [temporary file
uploads](#uploading-temporary-file), and pass the tokens returned by the API as
regular fields appended with a `Token` suffix. For example, to use previously
uploaded data, which was given token `deadbeef`, in an API that accepts a file
named `content`, the client should pass `{"contentToken":"deadbeef"}` as part
of the JSON message body. If the file with the particular token doesn't exist
or it has expired, the server will show an error.

## Error handling

All errors (except for unhandled fatal server errors) send relevant HTTP status
code together with JSON of following structure:

```json5
{
    "name": "Name of the error, e.g. 'PostNotFoundError'",
    "title": "Generic title of error message, e.g. 'Not found'",
    "description": "Detailed description of what went wrong, e.g. 'User `rr-` not found."
}
```

List of possible error names:

- `MissingRequiredFileError`
- `MissingRequiredParameterError`
- `InvalidParameterError` (when trying to pass text when integer is expected etc.)
- `IntegrityError` (race conditions when editing the same resource)
- `SearchError`
- `AuthError`
- `PostNotFoundError`
- `PostAlreadyFeaturedError`
- `PostAlreadyUploadedError`
- `InvalidPostIdError`
- `InvalidPostSafetyError`
- `InvalidPostSourceError`
- `InvalidPostContentError`
- `InvalidPostRelationError`
- `InvalidPostNoteError`
- `InvalidPostFlagError`
- `InvalidFavoriteTargetError`
- `InvalidCommentIdError`
- `CommentNotFoundError`
- `EmptyCommentTextError`
- `InvalidScoreTargetError`
- `InvalidScoreValueError`
- `TagCategoryNotFoundError`
- `TagCategoryAlreadyExistsError`
- `TagCategoryIsInUseError`
- `InvalidTagCategoryNameError`
- `InvalidTagCategoryColorError`
- `TagNotFoundError`
- `TagAlreadyExistsError`
- `TagIsInUseError`
- `InvalidTagNameError`
- `InvalidTagRelationError`
- `InvalidTagCategoryError`
- `InvalidTagDescriptionError`
- `UserNotFoundError`
- `UserAlreadyExistsError`
- `InvalidUserNameError`
- `InvalidEmailError`
- `InvalidPasswordError`
- `InvalidRankError`
- `InvalidAvatarError`
- `ProcessingError` (failed to generate thumbnail or download remote file)
- `ValidationError` (catch all for odd validation errors)


## Field selecting

For performance considerations, sometimes the client might want to choose the
fields the server sends to it in order to improve the query speed. This
customization is available for top-level fields of most of the
[resources](#resources). To choose the fields, the client should pass
`?fields=field1,field2,...` suffix to the query. This works regardless of the
request type (`GET`, `PUT` etc.).

For example, to list posts while getting only their IDs and tags, the client
should send a `GET` query like this:

```
GET /posts/?fields=id,tags
```

## Versioning

To prevent problems with concurrent resource modification, szurubooru
implements optimistic locks using resource versions. Each modifiable resource
has its `version` returned to the client with `GET` requests. At the same time,
each `PUT` and `DELETE` request sent by the client must present the same
`version` field to the server with value as it was given in `GET`.

For example, given `GET /post/1`, the server responds like this:

```
{
    ...,
    "version": 2
}
```

This means the client must then send `{"version": 2}` back too. If the client
fails to do so, the server will reject the request notifying about missing
parameter. If someone has edited the post in the mean time, the server will
reject the request as well, in which case the client is encouraged to notify
the user about the situation.


## Modules

A site can switch on optional modules (the `modules` setting of the server).
`GET /info` names the ones that are on, in its `modules` field, so a client
can tell what the site offers before using it.
What a module adds to the API is its own:

- routes under `modules/<name>/`;
- file types the engine does not know, with a post `type` and a `mimeType`
  of their own (see the [post resource](#post)); the `type` search token
  finds them by that type;
- [extracted content](#extracted-content) of the kinds it owns;
- named tokens of the [post search](#post-search);
- extra fields of the [post resource](#post). Some of them are returned
  only when the request names them in `fields`; the module says which.

A module never changes or removes a route, token or field of the engine.

`doc/openapi.json` describes the routes of every module, each under a tag
that is the module's name. A route of a module exists only on a site that
has the module switched on, and is 404 elsewhere: check `modules` of
`GET /info`. With `api_docs` on, the `openapi.json` a site serves has the
routes of that site's modules only.

### The cards module

`cards` makes a post of a character card for AI chat programs: a PNG picture
with the card in a text chunk, or a CHARX file (post `type` `charx`). What it
adds:

- **Tags.** A post gets its card's creator as a tag in the category
  `creator`, and the card's own tags in the default category, when the file
  is uploaded.
- **Search tokens.** `card-creator:<pattern>`, `card-spec:v1|v2|v3`,
  `card-format:png|charx`, `card-lorebook:yes|no` and
  `card-greetings:<number or range>`.
- **Post field `card`**, returned only when `fields` names it: `name`,
  `creator`, `spec`, `format`, `greetingCount` and `lorebookEntryCount`, or
  `null` for a post without a card.
- **`GET modules/cards/post/<id>`**: the card read for a viewer, the same
  shape for every version of the format and both kinds of file.
- **`GET modules/cards/post/<id>/download`**: the stored file, unchanged, as
  an attachment named after the character. This route answers with the file
  and does not require `Accept: application/json`.

The card as its file had it is the post's
[extracted content](#extracted-content), of the kind `card_v1`, `card_v2` or
`card_v3`. `doc/openapi.json` has the reference of the two routes.

## Webhooks

System administrators can choose to configure webhooks to track events.
Webhook URIs can be configured in `config.yaml` (See `config.yaml.dist` for
example). Upon any event, the API will send a `POST` request to the listed
URIs with a [snapshot resource](#snapshot) generated with anonymous user
privileges as the message body, in JSON format.


# Resources

## User
**Description**

A single user.

**Structure**

```json5
{
    "version":           <version>,
    "name":              <name>,
    "email":             <email>,
    "rank":              <rank>,
    "lastLoginTime":     <last-login-time>,
    "creationTime":      <creation-time>,
    "avatarStyle":       <avatar-style>,
    "avatarUrl":         <avatar-url>,
    "commentCount":      <comment-count>,
    "uploadedPostCount": <uploaded-post-count>,
    "likedPostCount":    <liked-post-count>,
    "dislikedPostCount": <disliked-post-count>,
    "favoritePostCount": <favorite-post-count>
}
```

**Field meaning**
- `<version>`: resource version. See [versioning](#versioning).
- `<name>`: the user name.
- `<email>`: the user email. It is available only if the request is
  authenticated by the same user, or the authenticated user can change the
  email. If it's unavailable, the server returns `false`. If the user hasn't
  specified an email, the server returns `null`.
- `<rank>`: the user rank, which effectively affects their privileges.

    Possible values:

    - `"restricted"`: restricted user
    - `"regular"`: regular user
    - `"power"`: power user
    - `"moderator"`: moderator
    - `"administrator"`: administrator

- `<last-login-time>`: the last login time, formatted as per RFC 3339.
- `<creation-time>`: the user registration time, formatted as per RFC 3339.
- `<avatarStyle>`: how to render the user avatar.

    Possible values:

    - `"gravatar"`: the user uses Gravatar.
    - `"manual"`: the user has uploaded a picture manually.

- `<avatarUrl>`: the URL to the avatar.
- `<comment-count>`: number of comments.
- `<uploaded-post-count>`: number of uploaded posts.
- `<liked-post-count>`: nubmer of liked posts. It is available only if the
  request is authenticated by the same user. If it's unavailable, the server
  returns `false`.
- `<disliked-post-count>`: number of disliked posts. It is available only if
  the request is authenticated by the same user. If it's unavailable, the
  server returns `false`.
- `<favorite-post-count>`: number of favorited posts.

## Micro user
**Description**

A [user resource](#user) stripped down to `name` and `avatarUrl` fields.

## User token
**Description**

A single user token.

**Structure**

```json5
{
    "user":           <user>,
    "token":          <token>,
    "note":           <token>,
    "enabled":        <enabled>,
    "expirationTime": <expiration-time>,
    "version":        <version>,
    "creationTime":   <creation-time>,
    "lastEditTime":   <last-edit-time>,
    "lastUsageTime":  <last-usage-time>
}
```

**Field meaning**
- `<user>`: micro user. See [micro user](#micro-user).
- `<token>`: the token that can be used to authenticate the user.
- `<note>`: a note that describes the token.
- `<enabled>`: whether the token is still valid for authentication.
- `<expiration-time>`: time when the token expires. It must include the timezone as per RFC 3339.
- `<version>`: resource version. See [versioning](#versioning).
- `<creation-time>`: time the user token was created, formatted as per RFC 3339.
- `<last-edit-time>`: time the user token was edited, formatted as per RFC 3339.
- `<last-usage-time>`: the last time this token was used during a login involving `?bump-login`, formatted as per RFC 3339.

## Tag category
**Description**

A single tag category. The primary purpose of tag categories is to distinguish
certain tag types (such as characters, media type etc.), which improves user
experience.

**Structure**

```json5
{
    "version": <version>,
    "name":    <name>,
    "color":   <color>,
    "usages":  <usages>,
    "order":   <order>,
    "default": <is-default>
}
```

**Field meaning**

- `<version>`: resource version. See [versioning](#versioning).
- `<name>`: the category name.
- `<color>`: the category color.
- `<usages>`: how many tags is the given category used with.
- `<order>`: the order in which tags with this category are displayed, ascending.
- `<is-default>`: whether the tag category is the default one.

## Tag
**Description**

A single tag. Tags are used to let users search for posts.

**Structure**

```json5
{
    "version":      <version>,
    "names":        <names>,
    "category":     <category>,
    "implications": <implications>,
    "suggestions":  <suggestions>,
    "creationTime": <creation-time>,
    "lastEditTime": <last-edit-time>,
    "usages":       <usage-count>,
    "description":  <description>
}
```

**Field meaning**

- `<version>`: resource version. See [versioning](#versioning).
- `<names>`: a list of tag names (aliases). Tagging a post with any name will
  automatically assign the first name from this list.
- `<category>`: the name of the category the given tag belongs to.
- `<implications>`: a list of implied tags, serialized as [micro
  tag resource](#micro-tag). Implied tags are automatically appended by the web
  client on usage.
- `<suggestions>`: a list of suggested tags, serialized as [micro
  tag resource](#micro-tag). Suggested tags are shown to the user by the web
  client on usage.
- `<creation-time>`: time the tag was created, formatted as per RFC 3339.
- `<last-edit-time>`: time the tag was edited, formatted as per RFC 3339.
- `<usage-count>`: the number of posts the tag was used in.
- `<description>`: the tag description (instructions how to use, history etc.)
  The client should render is as Markdown.

## Micro tag
**Description**

A [tag resource](#tag) stripped down to `names`, `category` and `usages` fields.

## Post
**Description**

One file together with its metadata posted to the site.

**Structure**

```json5
{
    "version":            <version>,
    "id":                 <id>,
    "creationTime":       <creation-time>,
    "lastEditTime":       <last-edit-time>,
    "safety":             <safety>,
    "source":             <source>,
    "type":               <type>,
    "checksum":           <checksum>,
    "checksumMD5":        <checksum-MD5>,
    "canvasWidth":        <canvas-width>,
    "canvasHeight":       <canvas-height>,
    "contentUrl":         <content-url>,
    "thumbnailUrl":       <thumbnail-url>,
    "flags":              <flags>,
    "tags":               <tags>,
    "relations":          <relations>,
    "notes":              <notes>,
    "user":               <user>,
    "score":              <score>,
    "ownScore":           <own-score>,
    "ownFavorite":        <own-favorite>,
    "tagCount":           <tag-count>,
    "favoriteCount":      <favorite-count>,
    "commentCount":       <comment-count>,
    "noteCount":          <note-count>,
    "featureCount":       <feature-count>,
    "relationCount":      <relation-count>,
    "lastFeatureTime":    <last-feature-time>,
    "favoritedBy":        <favorited-by>,
    "hasCustomThumbnail": <has-custom-thumbnail>,
    "mimeType":           <mime-type>,
    "comments": [
        <comment>,
        <comment>,
        <comment>
    ],
    "pools": [
        <pool>,
        <pool>,
        <pool>
    ],
    "contentKinds":       <content-kinds>
}
```

**Field meaning**

- `<version>`: resource version. See [versioning](#versioning).
- `<id>`: the post identifier.
- `<creation-time>`: time the tag was created, formatted as per RFC 3339.
- `<last-edit-time>`: time the tag was edited, formatted as per RFC 3339.
- `<safety>`: whether the post is safe for work.

    Available values:

    - `"safe"`
    - `"sketchy"`
    - `"unsafe"`

- `<source>`: where the post was grabbed form, supplied by the user.
- `<type>`: the type of the post.

    Available values:

    - `"image"` - plain image.
    - `"animation"` - animated image (GIF).
    - `"video"` - WEBM video.
    - `"flash"` - Flash animation / game.
    - `"youtube"` - Youtube embed.

    A [module](#modules) may add file types of its own. A post made from
    such a file has a `<type>` the module names (never one of the above),
    no canvas size, and a thumbnail the module takes from the file or the
    placeholder. A client that does not know a type should treat the post
    as a file to download.

- `<checksum>`: the SHA1 file checksum. Used in snapshots to signify changes of the
  post content.
- `<checksum-MD5>`: the MD5 file checksum.
- `<canvas-width>` and `<canvas-height>`: the original width and height of the
  post content.
- `<content-url>`: where the post content is located.
- `<thumbnail-url>`: where the post thumbnail is located.
- `<flags>`: various flags such as whether the post is looped, represented as
  array of plain strings.
- `<tags>`: list of tags the post is tagged with, serialized as [micro
  tag resource](#micro-tag).
- `<relations>`: a list of related posts, serialized as [micro post
  resources](#micro-post). Links to related posts are shown
  to the user by the web client.
- `<notes>`: a list of post annotations, serialized as list of [note
  resources](#note).
- `<user>`: who created the post, serialized as [micro user resource](#micro-user).
- `<score>`: the collective score (+1/-1 rating) of the given post.
- `<own-score>`: the score (+1/-1 rating) of the given post by the
  authenticated user.
- `<own-favorite>`: whether the authenticated user has given post in their
  favorites.
- `<tag-count>`: how many tags the post is tagged with
- `<favorite-count>`: how many users have the post in their favorites
- `<comment-count>`: how many comments are filed under that post
- `<note-count>`: how many notes the post has
- `<feature-count>`: how many times has the post been featured.
- `<relation-count>`: how many posts are related to this post.
- `<last-feature-time>`: the last time the post was featured, formatted as per
  RFC 3339.
- `<favorited-by>`: list of users, serialized as [micro user resources](#micro-user).
- `<has-custom-thumbnail>`: whether the post uses custom thumbnail.
- `<mime-type>`: subsidiary to `<type>`, used to tell exact content format;
  useful for `<video>` tags for instance.
- `<comment>`: a [comment resource](#comment) for given post.
- `<pool>`: a [micro pool resource](#micro-pool) in which the post is a member of.
- `<content-kinds>`: the kinds of [extracted content](#extracted-content) the
  post has, as a list of strings. Always empty on a site without modules.

## Extracted content
**Description**

Many files carry more than a picture: PNG text chunks, EXIF, the metadata of a
video. The engine itself does not read any of it. The optional
[modules](#modules) of a site do: when a post gets its file, they extract what
they understand, and the site keeps it with the post.

`GET /post/<id>/content` returns it as an [unpaged search
result](#unpaged-search-result) of the following resource. A post can have any
number of them, also several of one kind.

**Structure**

```json5
{
    "kind":          <kind>,
    "schemaVersion": <schema-version>,
    "extractedAt":   <extracted-at>,
    "content":       <content>
}
```

**Field meaning**

- `<kind>`: what the content is, for example `"dummy_v1"`. Every kind belongs
  to one module.
- `<schema-version>`: the version of the kind's format the content was
  extracted with.
- `<extracted-at>`: when it was extracted, formatted as per RFC 3339.
- `<content>`: the content itself. Its shape depends on the kind and is
  documented by the module the kind belongs to.

Content of a kind whose module is switched off is kept, but not returned.

A module can mark fields of its content as private. Those are left out unless
the requester has the `posts:view:content:private` privilege (moderators, by
default).

## Micro post
**Description**

A [post resource](#post) stripped down to `id` and `thumbnailUrl` fields.

## Note
**Description**

A text annotation rendered on top of the post.

**Structure**

```json5
{
    "polygon": <list-of-points>,
    "text":    <text>,
}
```

**Field meaning**
- `<list-of-points>`: where to draw the annotation. Each point must have
  coordinates within 0 to 1. For example, `[[0,0],[0,1],[1,1],[1,0]]` will draw
  the annotation on the whole post, whereas `[[0,0],[0,0.5],[0.5,0.5],[0.5,0]]`
  will draw it inside the post's upper left quarter.
- `<text>`: the annotation text. The client should render is as Markdown.

## Pool category
**Description**

A single pool category. The primary purpose of pool categories is to distinguish
certain pool types (such as series, relations etc.), which improves user
experience.

**Structure**

```json5
{
    "version": <version>,
    "name":    <name>,
    "color":   <color>,
    "usages":  <usages>,
    "default": <is-default>
}
```

**Field meaning**

- `<version>`: resource version. See [versioning](#versioning).
- `<name>`: the category name.
- `<color>`: the category color.
- `<usages>`: how many pools is the given category used with.
- `<is-default>`: whether the pool category is the default one.

## Pool
**Description**

An ordered list of posts, with a description and category.

**Structure**

```json5
{
    "version":      <version>,
    "id":           <id>,
    "names":        <names>,
    "category":     <category>,
    "posts":        <suggestions>,
    "creationTime": <creation-time>,
    "lastEditTime": <last-edit-time>,
    "postCount":   <post-count>,
    "description":  <description>
}
```

**Field meaning**

- `<version>`: resource version. See [versioning](#versioning).
- `<id>`: the pool identifier.
- `<names>`: a list of pool names (aliases).
- `<category>`: the name of the category the given pool belongs to.
- `<posts>`: an ordered list of posts, serialized as [micro
  post resource](#micro-post). Posts are ordered by insertion by default.
- `<creation-time>`: time the pool was created, formatted as per RFC 3339.
- `<last-edit-time>`: time the pool was edited, formatted as per RFC 3339.
- `<post-count>`: the number of posts the pool has.
- `<description>`: the pool description (instructions how to use, history etc.)
  The client should render it as Markdown.

## Micro pool
**Description**

A [pool resource](#pool) stripped down to `id`, `names`, `category`,
`description` and `postCount` fields.

## Comment
**Description**

A comment under a post.

**Structure**

```json5
{
    "version":      <version>,
    "id":           <id>,
    "postId":       <post-id>,
    "user":         <author>,
    "text":         <text>,
    "creationTime": <creation-time>,
    "lastEditTime": <last-edit-time>,
    "score":        <score>,
    "ownScore":     <own-score>
}
```

**Field meaning**
- `<version>`: resource version. See [versioning](#versioning).
- `<id>`: the comment identifier.
- `<post-id>`: an id of the post the comment is for.
- `<text>`: the comment content. The client should render is as Markdown.
- `<author>`: a [micro user resource](#micro-user) the comment is created by.
- `<creation-time>`: time the comment was created, formatted as per RFC 3339.
- `<last-edit-time>`: time the comment was edited, formatted as per RFC 3339.
- `<score>`: the collective score (+1/-1 rating) of the given comment.
- `<own-score>`: the score (+1/-1 rating) of the given comment by the
  authenticated user.

## Snapshot
**Description**

A snapshot is a version of a database resource.

**Structure**

```json5
{
    "operation": <operation>,
    "type":      <resource-type>,
    "id":        <resource-id>,
    "user":      <issuer>,
    "data":      <data>,
    "time":      <time>
}
```

**Field meaning**

- `<operation>`: what happened to the resource.

    The value can be either of values below:

    - `"created"` - the resource has been created
    - `"modified"` - the resource has been modified
    - `"deleted"` - the resource has been deleted
    - `"merged"` - the resource has been merged to another resource

- `<resource-type>` and `<resource-id>`: the resource that was changed.

    The values are correlated as per table below:

    | `<resource-type>` | `<resource-id>`                 |
    | ----------------- | ------------------------------- |
    | `"tag"`           | first tag name at given time    |
    | `"tag_category"`  | tag category name at given time |
    | `"post"`          | post ID                         |
    | `"pool"`          | pool ID                         |

- `<issuer>`: a [micro user resource](#micro-user) representing the user who
    has made the change.

- `<data>`: the snapshot data, of which content depends on the `<operation>`.
   More explained later.

- `<time>`: when the snapshot was created (i.e. when the resource was changed),
  formatted as per RFC 3339.

**`<data>` field for creation snapshots**

The value can be either of structures below, depending on
`<resource-type>`:

- Tag category snapshot data (`<resource-type> = "tag_category"`)

    *Example*

    ```json5
    {
        "name":  "character",
        "color": "#FF0000",
        "default": false
    }
    ```

- Tag snapshot data (`<resource-type> = "tag"`)

    *Example*

    ```json5
    {
        "names":        ["tag1", "tag2", "tag3"],
        "category":     "plain",
        "implications": ["imp1", "imp2", "imp3"],
        "suggestions":  ["sug1", "sug2", "sug3"]
    }
    ```

- Post snapshot data (`<resource-type> = "post"`)

    *Example*

    ```json5
    {
        "source": "http://example.com/",
        "safety": "safe",
        "checksum": "deadbeef",
        "tags": ["tag1", "tag2"],
        "relations": [1, 2],
        "notes": [<note1>, <note2>, <note3>],
        "flags": ["loop"],
        "featured": false
    }
    ```

    `<note>`s are serialized the same way as [note resources](#note).

**`<data>` field for modification snapshots**

The value is a property-wise recursive diff between previous version of the
resource and its current version. Its structure is a `<dictionary-diff>` of
dictionaries as created by creation snapshots, which is described below.

`<primitive>`: any primitive (number or a string)

`<anything>`: any dictionary, list or primitive

`<dictionary-diff>`:

```json5
{
    "type": "object change",
    "value":
    {
        "property-of-any-type-1":
        {
            "type": "deleted property",
            "value": <anything>
        },
        "property-of-any-type-2":
        {
            "type": "added property",
            "value": <anything>
        },
        "primitive-property":
        {
            "type": "primitive change",
            "old-value": "<primitive>",
            "new-value": "<primitive>"
        },
        "list-property": <list-diff>,
        "dictionary-property": <dictionary-diff>
    }
}
```

`<list-diff>`:

```json5
{
    "type": "list change",
    "removed": [<anything>, <anything>],
    "added": [<anything>, <anything>]
}
```

Example - a diff for a post that has changed source and has one note added.
Note the similarities with the structure of post creation snapshots.

```json5
{
    "type": "object change",
    "value":
    {
        "source":
        {
            "type": "primitive change",
            "old-value": None,
            "new-value": "new source"
        },
        "notes":
        {
            "type": "list change",
            "removed": [],
            "added":
            [
                {"polygon": [[0, 0], [0, 1], [1, 1]], "text": "new note"}
            ]
        }
    }
}
```

Since the snapshot dictionaries structure is pretty immutable, you probably
won't see `added property` or `deleted property` around. This observation holds
true even if the way the snapshots are generated changes - szurubooru stores
just the diffs rather than original snapshots, so it wouldn't be able to
generate a diff against an old version.

**`<data>` field for deletion snapshots**

Same as creation snapshot. In emergencies, it can be used to reconstruct
deleted entities. Please note that this does not constitute as means against
vandalism (it's still possible to cause chaos by mass editing - this should be
dealt with by configuring role privileges in the config) or replace database
backups.

**`<data>` field for merge snapshots**

A tuple containing 2 elements:

- resource type equivalent to `<resource-type>` of the target entity.
- resource ID euivalen to `<resource-id>` of the target entity.


## Unpaged search result
**Description**

A result of search operation that doesn't involve paging.

**Structure**

```json5
{
    "results": [
        <resource>,
        <resource>,
        <resource>
    ]
}
```

**Field meaning**
- `<resource>`: any resource - which exactly depends on the API call. For
  details on this field, check the documentation for given API call.

## Paged search result
**Description**

A result of search operation that involves paging.

**Structure**

```json5
{
    "query":    <query>,  // same as in input
    "offset":   <offset>, // same as in input
    "limit":    <page-size>,
    "total":    <total-count>,
    "results": [
        <resource>,
        <resource>,
        <resource>
    ]
}
```

**Field meaning**
- `<query>`: the query passed in the original request that contains standard
  [search query](#search).
- `<offset>`: the record starting offset, passed in the original request.
- `<page-size>`: number of records on one page.
- `<total-count>`: how many resources were found. To get the page count, divide
  this number by `<page-size>`.
- `<resource>`: any resource - which exactly depends on the API call. For
  details on this field, check the documentation for given API call.


## Image search result
**Description**

A result of reverse image search operation.

**Structure**

```json5
{
    "exactPost": <exact-post>,
    "similarPosts": [
        {
            "distance": <distance>,
            "post": <similar-post>
        },
        {
            "distance": <distance>,
            "post": <similar-post>
        },
        ...
    ]
}
```

**Field meaning**
-  `exact-post`: a [post resource](#post) that is exact byte-to-byte duplicate
   of the input file. May be `null`.
- `<similar-post>`: a [post resource](#post) that isn't exact duplicate, but
   visually resembles the input file. Works only on images and animations, i.e.
   does not work for videos and Flash movies. For non-images and corrupted
   images, this list is empty.
- `<distance>`: distance from the original image (0..1). The lower this value
   is, the more similar the post is.


# Search

Search queries are built of tokens that are separated by spaces. Each token can
be of following form:

| Syntax            | Token type        | Description                                |
| ----------------- | ----------------- | ------------------------------------------ |
| `<value>`         | anonymous tokens  | basic filters                              |
| `<key>:<value>`   | named tokens      | advanced filters                           |
| `sort:<style>`    | sort style tokens | sort the results                           |
| `special:<value>` | special tokens    | filters usually tied to the logged in user |

Most of anonymous and named tokens support ranged and composite values that
take following form:

| `<value>` | Description                                           |
| --------- | ----------------------------------------------------- |
| `a,b,c`   | will show things that satisfy either `a`, `b` or `c`. |
| `1..`     | will show things that are equal to or greater than 1. |
| `..4`     | will show things that are equal to at most 4.         |
| `1..4`    | will show things that are equal to 1, 2, 3 or 4.      |

Ranged values can be also supplied by appending `-min` or `-max` to the key,
for example like this: `score-min:1`.

Date/time values can be of following form:

- `today`
- `yesterday`
- `<year>`
- `<year>-<month>`
- `<year>-<month>-<day>`

Some fields, such as user names, can take wildcards (`*`).

You can escape special characters such as `:` and `-` by prepending them with a
backslash: `\\`.

**Example**

Searching for posts with following query:

    sea -fav-count:8.. type:swf uploader:Pirate

will show flash files tagged as sea, that were liked by seven people at most,
uploaded by user Pirate.

Searching for posts with `re:zero` will show an error message about unknown
named token.

Searching for posts with `re\:zero` will show posts tagged with `re:zero`.

## Tag search

### Anonymous tokens

Same as `name` token.

### Named tokens

| `<key>`             | Description                               |
| ------------------- | ----------------------------------------- |
| `name`              | having given name (accepts wildcards)     |
| `category`          | having given category (accepts wildcards) |
| `creation-date`     | created at given date                     |
| `creation-time`     | alias of `creation-date`                  |
| `last-edit-date`    | edited at given date                      |
| `last-edit-time`    | alias of `last-edit-date`                 |
| `edit-date`         | alias of `last-edit-date`                 |
| `edit-time`         | alias of `last-edit-date`                 |
| `usages`            | used in given number of posts             |
| `usage-count`       | alias of `usages`                         |
| `post-count`        | alias of `usages`                         |
| `suggestion-count`  | with given number of suggestions          |
| `implication-count` | with given number of implications         |

### Sort style tokens

| `<value>`           | Description                  |
| ------------------- | ---------------------------- |
| `random`            | as random as it can get      |
| `name`              | A to Z                       |
| `category`          | category (A to Z)            |
| `creation-date`     | recently created first       |
| `creation-time`     | alias of `creation-date`     |
| `last-edit-date`    | recently edited first        |
| `last-edit-time`    | alias of `creation-time`     |
| `edit-date`         | alias of `creation-time`     |
| `edit-time`         | alias of `creation-time`     |
| `usages`            | used in most posts first     |
| `usage-count`       | alias of `usages`            |
| `post-count`        | alias of `usages`            |
| `suggestion-count`  | with most suggestions first  |
| `implication-count` | with most implications first |

### Special tokens

None.

## Post search

### Anonymous tokens

Same as `tag` token.

### Named tokens

| `<key>`              | Description                                                                                                                             |
| -------------------- | ----------------------------------------------------------                                                                              |
| `id`                 | having given post number                                                                                                                |
| `tag`                | having given tag (accepts wildcards)                                                                                                    |
| `score`              | having given score                                                                                                                      |
| `uploader`           | uploaded by given user (accepts wildcards)                                                                                              |
| `upload`             | alias of upload                                                                                                                         |
| `submit`             | alias of upload                                                                                                                         |
| `comment`            | commented by given user (accepts wildcards)                                                                                             |
| `fav`                | favorited by given user (accepts wildcards)                                                                                             |
| `pool`               | belonging to the pool with the given ID                                                                                                 |
| `tag-count`          | having given number of tags                                                                                                             |
| `comment-count`      | having given number of comments                                                                                                         |
| `fav-count`          | favorited by given number of users                                                                                                      |
| `note-count`         | having given number of annotations                                                                                                      |
| `note-text`          | having given note text (accepts wildcards)                                                                                              |
| `relation-count`     | having given number of relations                                                                                                        |
| `feature-count`      | having been featured given number of times                                                                                              |
| `type`               | given type of posts. `<value>` can be either `image`, `animation` (or `animated` or `anim`), `flash` (or `swf`) or `video` (or `webm`), or a type of a module that is switched on. |
| `content-checksum`   | having given SHA1 checksum                                                                                                              |
| `file-size`          | having given file size (in bytes)                                                                                                       |
| `image-width`        | having given image width (where applicable)                                                                                             |
| `image-height`       | having given image height (where applicable)                                                                                            |
| `image-area`         | having given number of pixels (image width * image height)                                                                              |
| `image-aspect-ratio` | having given aspect ratio (image width / image height)                                                                                  |
| `image-ar`           | alias of `image-aspect-ratio`                                                                                                           |
| `width`              | alias of `image-width`                                                                                                                  |
| `height`             | alias of `image-height`                                                                                                                 |
| `area`               | alias of `image-area`                                                                                                                   |
| `ar`                 | alias of `image-aspect-ratio`                                                                                                           |
| `aspect-ratio`       | alias of `image-aspect-ratio`                                                                                                           |
| `creation-date`      | posted at given date                                                                                                                    |
| `creation-time`      | alias of `creation-date`                                                                                                                |
| `date`               | alias of `creation-date`                                                                                                                |
| `time`               | alias of `creation-date`                                                                                                                |
| `last-edit-date`     | edited at given date                                                                                                                    |
| `last-edit-time`     | alias of `last-edit-date`                                                                                                               |
| `edit-date`          | alias of `last-edit-date`                                                                                                               |
| `edit-time`          | alias of `last-edit-date`                                                                                                               |
| `comment-date`       | commented at given date                                                                                                                 |
| `comment-time`       | alias of `comment-date`                                                                                                                 |
| `fav-date`           | last favorited at given date                                                                                                            |
| `fav-time`           | alias of `fav-date`                                                                                                                     |
| `feature-date`       | featured at given date                                                                                                                  |
| `feature-time`       | alias of `feature-time`                                                                                                                 |
| `safety`             | having given safety. `<value>` can be either `safe`, `sketchy` or `unsafe`.                                         |
| `rating`             | alias of `safety`                                                                                                                       |

### Sort style tokens

| `<value>`        | Description                                      |
| ---------------- | ------------------------------------------------ |
| `random`         | as random as it can get                          |
| `id`             | highest to lowest post number                    |
| `score`          | highest scored                                   |
| `tag-count`      | with most tags                                   |
| `comment-count`  | most commented first                             |
| `fav-count`      | loved by most                                    |
| `note-count`     | with most annotations                            |
| `relation-count` | with most relations                              |
| `feature-count`  | most often featured                              |
| `file-size`      | largest files first                              |
| `image-width`    | widest images first                              |
| `image-height`   | tallest images first                             |
| `image-area`     | largest images first                             |
| `width`          | alias of `image-width`                           |
| `height`         | alias of `image-height`                          |
| `area`           | alias of `image-area`                            |
| `creation-date`  | newest to oldest (pretty much same as id)        |
| `creation-time`  | alias of `creation-date`                         |
| `date`           | alias of `creation-date`                         |
| `time`           | alias of `creation-date`                         |
| `last-edit-date` | like creation-date, only looks at last edit time |
| `last-edit-time` | alias of `last-edit-date`                        |
| `edit-date`      | alias of `last-edit-date`                        |
| `edit-time`      | alias of `last-edit-date`                        |
| `comment-date`   | recently commented by anyone                     |
| `comment-time`   | alias of `comment-date`                          |
| `fav-date`       | recently added to favorites by anyone            |
| `fav-time`       | alias of `fav-date`                              |
| `feature-date`   | recently featured                                |
| `feature-time`   | alias of `feature-time`                          |

### Special tokens

| `<value>`    | Description                                                   |
| ------------ | ------------------------------------------------------------- |
| `liked`      | posts liked by currently logged in user                       |
| `disliked`   | posts disliked by currently logged in user                    |
| `fav`        | posts added to favorites by currently logged in user          |
| `tumbleweed` | posts with score of 0, without comments and without favorites |

## Pool search

### Anonymous tokens

Same as `name` token.

### Named tokens

| `<key>`             | Description                               |
| ------------------- | ----------------------------------------- |
| `name`              | having given name (accepts wildcards)     |
| `category`          | having given category (accepts wildcards) |
| `creation-date`     | created at given date                     |
| `creation-time`     | alias of `creation-date`                  |
| `last-edit-date`    | edited at given date                      |
| `last-edit-time`    | alias of `last-edit-date`                 |
| `edit-date`         | alias of `last-edit-date`                 |
| `edit-time`         | alias of `last-edit-date`                 |
| `post-count`        | used in given number of posts             |

### Sort style tokens

| `<value>`           | Description                  |
| ------------------- | ---------------------------- |
| `random`            | as random as it can get      |
| `name`              | A to Z                       |
| `category`          | category (A to Z)            |
| `creation-date`     | recently created first       |
| `creation-time`     | alias of `creation-date`     |
| `last-edit-date`    | recently edited first        |
| `last-edit-time`    | alias of `creation-time`     |
| `edit-date`         | alias of `creation-time`     |
| `edit-time`         | alias of `creation-time`     |
| `post-count`        | used in most posts first     |

### Special tokens

None.

## Comment search

### Anonymous tokens

Same as `text` token.

### Named tokens

| `<key>`          | Description                                    |
| ---------------- | ---------------------------------------------- |
| `id`             | specific comment ID                            |
| `post`           | specific post ID                               |
| `user`           | created by given user (accepts wildcards)      |
| `author`         | alias of `user`                                |
| `text`           | containing given text (accepts wildcards)      |
| `creation-date`  | created at given date                          |
| `creation-time`  | alias of `creation-date`                       |
| `last-edit-date` | whose most recent edit date matches given date |
| `last-edit-time` | alias of `last-edit-date`                      |
| `edit-date`      | alias of `last-edit-date`                      |
| `edit-time`      | alias of `last-edit-date`                      |

### Sort style tokens

| `<value>`        | Description               |
| ---------------- | ------------------------- |
| `random`         | as random as it can get   |
| `user`           | author name, A to Z       |
| `author`         | alias of `user`           |
| `post`           | post ID, newest to oldest |
| `creation-date`  | newest to oldest          |
| `creation-time`  | alias of `creation-date`  |
| `last-edit-date` | recently edited first     |
| `last-edit-time` | alias of `last-edit-date` |
| `edit-date`      | alias of `last-edit-date` |
| `edit-time`      | alias of `last-edit-date` |

### Special tokens

None.

## User search

### Anonymous tokens

Same as `name` token.

### Named tokens

| `<key>`           | Description                                     |
| ----------------- | ----------------------------------------------- |
| `name`            | having given name (accepts wildcards)           |
| `creation-date`   | registered at given date                        |
| `creation-time`   | alias of `creation-date`                        |
| `last-login-date` | whose most recent login date matches given date |
| `last-login-time` | alias of `last-login-date`                      |
| `login-date`      | alias of `last-login-date`                      |
| `login-time`      | alias of `last-login-date`                      |

### Sort style tokens

| `<value>`         | Description                |
| ----------------- | -------------------------- |
| `random`          | as random as it can get    |
| `name`            | A to Z                     |
| `creation-date`   | newest to oldest           |
| `creation-time`   | alias of `creation-date`   |
| `last-login-date` | recently active first      |
| `last-login-time` | alias of `last-login-date` |
| `login-date`      | alias of `last-login-date` |
| `login-time`      | alias of `last-login-date` |

### Special tokens

None.

## Snapshot search

### Anonymous tokens

Not supported.

### Named tokens

| `<key>`           | Description                                                      |
| ----------------- | ---------------------------------------------------------------- |
| `type`            | involving given resource type                                    |
| `id`              | involving given resource id                                      |
| `date`            | created at given date                                            |
| `time`            | alias of `date`                                                  |
| `operation`       | `modified`, `created`, `deleted` or `merged`                     |
| `user`            | name of the user that created given snapshot (accepts wildcards) |

### Sort style tokens

None. The snapshots are always sorted by creation time.

### Special tokens

None.
