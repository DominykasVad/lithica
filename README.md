# Lithica

Lithica is a self-hosted image board ("booru") engine for small and medium
communities, in the style of Danbooru, Gelbooru and Moebooru. Optional
features are planned as modules layered on top of the generic engine.

> **This is a modified fork of [szurubooru](https://github.com/rr-/szurubooru).**
> Lithica was forked from szurubooru at upstream commit `10ac850` (tagged
> `fork-point`) and has been modified since 2026-10-10. It is developed
> independently and does not track upstream. The original work is copyright
> its authors and, like this fork, is licensed under the GPLv3.

Lithica is under active restructuring (see [PLAN.md](PLAN.md)); there is no
stable release yet.

## Features

- Post content: images (JPG, PNG, GIF, animated GIF), videos (MP4, WEBM), Flash animations
- Ability to retrieve web video content using [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- Post comments
- Post notes / annotations, including arbitrary polygons
- Rich JSON REST API ([see documentation](doc/API.md))
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
[See installation instructions.](doc/INSTALL.md)

The [upstream szurubooru wiki](https://github.com/rr-/szurubooru/wiki) has
more installation resources and related projects; they were written for
szurubooru and may not match Lithica.

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
