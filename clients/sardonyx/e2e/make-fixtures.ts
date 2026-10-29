/**
 * Writes the cards the browser tests import (fixtures/cards): small ones,
 * made by cards.ts. Run again after changing them:
 *
 *   node e2e/make-fixtures.ts      (from clients/sardonyx)
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { charxCard, picture, pngCard, v2Card, v3Card } from "./cards.ts";

const folder = path.join(import.meta.dirname, "fixtures", "cards");
mkdirSync(folder, { recursive: true });

const write = (name: string, data: Buffer) =>
  writeFileSync(path.join(folder, name), data);

// a V2 PNG card with a lorebook and greetings
write(
  "harbour-keeper-v2.png",
  pngCard(
    v2Card({ name: "Harbour Keeper", creator: "e2e_maker", greetings: 3, entries: 6 }),
    1,
  ),
);
// a V3 PNG card
write(
  "lantern-signal-v3.png",
  pngCard(
    v3Card({ name: "Lantern Signal", creator: "e2e_maker", greetings: 1, entries: 12 }),
    2,
  ),
);
// a CHARX card (V3 inside)
write(
  "tidewarden.charx",
  charxCard(v3Card({ name: "Tidewarden", creator: "e2e_other", entries: 3 }), 3),
);
// a card whose HTML tries to reach out of its frame, and asks for an image
write(
  "styled-probe-v2.png",
  pngCard(
    v2Card({
      name: "Styled Probe",
      creator: "e2e_maker",
      description: [
        '<div class="probe" style="color: rgb(200, 30, 30)">Styled probe text</div>',
        '<img src="https://e2e-images.example/probe.png" alt="probe picture">',
        "<script>try { parent.postMessage('probe-script', '*') } catch (e) {}</script>",
        "<script>try { top.document.title = 'probe' } catch (e) {}</script>",
        "<script>try { localStorage.setItem('probe', '1') } catch (e) {}</script>",
        "<img src=\"x\" onerror=\"parent.postMessage('probe-onerror', '*')\">",
      ].join("\n"),
    }),
    4,
  ),
);
// a NSFW card: its own tags say so
write(
  "night-shift-v2.png",
  pngCard(v2Card({ name: "Night Shift", creator: "e2e_maker", tags: ["nsfw"] }), 5),
);
// a picture that is not a card
write("plain-picture.png", picture(6));
