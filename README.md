# Lithica

Lithica is a self-hosted image board ("booru") engine for small and medium
communities, in the style of Danbooru, Gelbooru and Moebooru. Optional
features are modules layered on top of the generic engine and switched on
in the configuration.

> **This is a modified fork of [szurubooru](https://github.com/rr-/szurubooru).**
> Lithica was forked from szurubooru at upstream commit `10ac850` (tagged
> `fork-point`) and has been modified since 2026-10-10. It is developed
> independently and does not track upstream. The original work is copyright
> its authors and, like this fork, is licensed under the GPLv3.

`v0.1.0` was the engine, modernised, and the module system. `v0.2.0` adds the
first module, `cards`: character cards for AI chat programs as posts, from
PNG pictures and CHARX files. `v0.3.0` adds Sardonyx, a new web client and
the default one, which is a card library when `cards` is on; the bulk
import of a folder; and settings for what visitors see without logging in.
The legacy client stays available beside it. Versions are `v0.x` until the project is called
stable; [PLAN.md](PLAN.md) has the roadmap.

## Features

- Post content: images (JPG, PNG, GIF, animated GIF), videos (MP4, WEBM), Flash animations
- Ability to retrieve web video content using [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- Post comments
- Post notes / annotations, including arbitrary polygons
- Rich JSON REST API ([see documentation](doc/API.md)), with an OpenAPI contract ([doc/openapi.json](doc/openapi.json))
- Optional modules that read content embedded in uploaded files, tag posts from it and extend the search and the API
- Token based authentication for clients
- Rich search system
- Rich privilege system
- Autocomplete in search and while editing tags
- Tag categories
- Tag suggestions
- Tag implications (adding a tag automatically adds another)
- Tag aliases
- Pools and pool categories
- Duplicate detection
- Post rating and favoriting; comment rating
- Polished UI
- Browser configurable endless paging
- Browser configurable backdrop grid for transparent images

## Installation

It is recommended that you use Docker for deployment.
[See installation instructions.](doc/INSTALL.md) To move an existing
szurubooru site to Lithica, see [UPGRADING.md](doc/UPGRADING.md).

The [upstream szurubooru wiki](https://github.com/rr-/szurubooru/wiki) has
more installation resources and related projects; they were written for
szurubooru and may not match Lithica.

## Who sees what

A site decides what visitors who are not logged in may see (`visibility`
in `server/config.yaml`; [doc/API.md](doc/API.md#visibility) has the
details):

- `open`, the default: as the privileges of the anonymous rank say.
- `nsfw-login`: posts tagged with the NSFW tag (`nsfw_tag`, default
  `nsfw`), or with a tag that implies it, do not exist for visitors who are
  not logged in: not in searches, not by their address, not their card,
  comments or snapshots. Numbers still count them: tag usages and the tags
  shown beside a tag, a pool's post count, a user's upload and favourite
  counts. Never their ids, addresses, files or cards. (Listing tags needs
  the `tags:list` privilege, which visitors do not have by default.)
- `login`: nothing but logging in and password reset without logging in;
  signing up is closed too.

With `nsfw_hide_names: true`, Sardonyx also hides a NSFW card's name and
creator until the viewer reveals the post or turns on Show NSFW (a hint to
clients: the API still gives the names to whoever may see the post).

Without a `file_link_secret`, post files stay reachable by anyone who has
their address; the server warns of it at start. See
[Signed file links](#signed-file-links).

### Signed file links

The files of posts are served by the web server in front, not by the API,
at addresses that are hard to guess but valid for good: whoever has one can
open it, logged in or not, and so can anybody it is passed on to. With
signed file links, every address the server gives out ends with an expiry
and a signature, and the web server serves a post's file or thumbnail only
to such an address, for one to two days. That keeps the files to those the
API showed them to: a visitor of a `nsfw-login` site never gets an address
of a NSFW post, and an address someone copied stops working.

It does not take back a file someone has already downloaded, nor an address
while it is valid. Avatars are not signed.

To switch it on, set `FILE_LINK_SECRET` in `.env` to a long random string
(letters, digits, `-` and `_`, at least 32; `openssl rand -hex 32` makes
one). The compose files pass it to the server and to the client images,
which check the links. Changing it ends every link handed out so far; the
apps simply ask the API again. Without it, file addresses are as they
always were.

## Screenshots

Screenshots of the legacy client inherited from szurubooru.

Post list:

![20160908_180032_fsk](https://cloud.githubusercontent.com/assets/1045476/18356730/3f1123d6-75ee-11e6-85dd-88a7615243a0.png)

Post view:

![20160908_180429_lmp](https://cloud.githubusercontent.com/assets/1045476/18356731/3f1566ee-75ee-11e6-9594-e86ca7347b0f.png)

## License

[GPLv3](LICENSE.md). Lithica is a modified version of szurubooru; the changes
made since the fork are in this repository's history after the `fork-point`
tag. Original copyright and attribution are retained.

The server and the repository as a whole are GPLv3. One folder has a licence
of its own: `clients/sardonyx/`, the new web client, is MIT. See
[LICENSING.md](LICENSING.md).
