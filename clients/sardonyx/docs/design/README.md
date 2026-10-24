# Sardonyx design reference

The source files of the Sardonyx design canvas (as of 2026-10-24), one per board:

| File | Board |
| --- | --- |
| `Main.dc.html` | Card viewer |
| `Gallery.dc.html` | Library (gallery and search) |
| `Lorebook.dc.html` | Lorebook view |
| `Style.dc.html` | Light style tile |
| `DarkTile.dc.html` | Dark style tile; its `theme` switches between `sardonyx`, `dracula` and `gruvbox` |
| `DarkDracula.dc.html`, `DarkGruvbox.dc.html` | The dark tile with that theme |
| `canvas.json` | Board titles, sizes and order |

They are read as source, not opened in a browser: the canvas runtime they load
(`support.js`) is not part of this repository. Markup is plain HTML with inline
styles; `{{…}}` are template values filled by the class at the bottom of each file.

This is a direction, not a spec. Follow its layout, hierarchy, type and colour
roles; build with the client's components and tokens, never copy its markup or
inline styles. Where it disagrees with PLAN.md or a brief, those win.

Do not edit these files. A newer design replaces them all and updates the
date above.
