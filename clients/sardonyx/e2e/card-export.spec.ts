/** Request-level e2e check for PNG card export with share links. */
import { randomInt } from "node:crypto";
import { expect, test } from "@playwright/test";
import { picture, v3Card } from "./cards.ts";
import { ADMIN, api, SITE, upload } from "./support.ts";

const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function readPngChunk(pngBytes: Buffer, keyword: string): Record<string, unknown> {
  expect(pngBytes.subarray(0, 8)).toEqual(PNG_SIGNATURE);
  let offset = 8;
  while (offset + 12 <= pngBytes.length) {
    const length = pngBytes.readUInt32BE(offset);
    const type = pngBytes.subarray(offset + 4, offset + 8).toString("latin1");
    const data = pngBytes.subarray(offset + 8, offset + 8 + length);
    if (type === "tEXt") {
      const nul = data.indexOf(0);
      if (nul !== -1 && data.subarray(0, nul).toString("latin1") === keyword) {
        const b64 = data.subarray(nul + 1).toString("ascii");
        return JSON.parse(Buffer.from(b64, "base64").toString("utf8")) as Record<
          string,
          unknown
        >;
      }
    }
    if (type === "IEND") {
      break;
    }
    offset += 12 + length;
  }
  throw new Error(`PNG chunk ${keyword} not found`);
}

test("PNG export with share links delivers images without login and respects revoke", async ({
  request,
}) => {
  const seed = randomInt(1_000_000);
  const avatarBytes = picture(seed);
  const exprBytes = picture(seed + 1);
  const textBytes = picture(seed + 2);

  const avatarPost = await upload(request, "export-avatar.png", avatarBytes);
  const exprPost = await upload(request, "export-expr.png", exprBytes);
  const textPost = await upload(request, "export-text.png", textBytes);

  const card = v3Card({
    name: `Export Links ${seed}`,
    creator: "Lithica tests",
  });
  card.data.first_mes = `Look: ![pic](lithica:post/${String(textPost.id)})`;

  const created = await api(request, "POST", "/modules/cards/cards", {
    user: ADMIN,
    data: {
      safety: "safe",
      card,
      images: [
        { role: "avatar", postId: avatarPost.id },
        { role: "expression", postId: exprPost.id, label: "smile" },
      ],
    },
  });
  expect(created.status).toBe(200);
  const cardId = (created.body.post as { id: number }).id;

  const basic = `Basic ${Buffer.from(`${ADMIN.name}:${ADMIN.password}`).toString("base64")}`;
  const exported = await request.post(
    `${SITE}/api/modules/cards/post/${cardId}/export`,
    {
      headers: { Authorization: basic },
      data: { format: "png", spec: "v3+v2", images: "links" },
    },
  );
  expect(exported.status()).toBe(200);
  expect(exported.headers()["content-type"]).toBe("image/png");
  expect(exported.headers()["x-content-type-options"]).toBe("nosniff");
  expect(exported.headers()["cache-control"]).toBe("no-store");
  expect(exported.headers()["x-lithica-export-skipped"]).toBe("0");

  const pngBytes = await exported.body();
  const parsed = readPngChunk(pngBytes, "ccv3");
  const data = parsed.data as {
    first_mes: string;
    assets: { type: string; uri: string; name: string }[];
  };
  expect(data.assets[0]?.uri).toBe("ccdefault:");
  const exprUrl = data.assets.find((a) => a.name === "smile")?.uri ?? "";
  expect(exprUrl).toMatch(/^https?:\/\/.+\/share\/[A-Za-z0-9_-]+$/);

  const textMatch = data.first_mes.match(/!\[pic\]\(([^)]+)\)/);
  const textUrl = textMatch?.[1] ?? "";
  expect(textUrl).toMatch(/^https?:\/\/.+\/share\/[A-Za-z0-9_-]+$/);

  // Every share link in the export works without login and returns the image bytes.
  const exprResp = await request.get(exprUrl);
  expect(exprResp.status()).toBe(200);
  expect(await exprResp.body()).toEqual(exprBytes);

  const textResp = await request.get(textUrl);
  expect(textResp.status()).toBe(200);
  expect(await textResp.body()).toEqual(textBytes);

  // Revoke the expression's share link -> 404; the other link still works.
  const links = await api(request, "GET", `/post/${String(exprPost.id)}/share-links`, {
    user: ADMIN,
  });
  expect(links.status).toBe(200);
  const exportLink = (links.body.results as { id: number; note: string | null }[]).find(
    (l) => l.note === "Card export",
  );
  expect(exportLink).toBeDefined();
  const revoked = await api(
    request,
    "DELETE",
    `/share-link/${String(exportLink?.id)}`,
    { user: ADMIN },
  );
  expect(revoked.status).toBe(200);
  expect((await request.get(exprUrl)).status()).toBe(404);
  expect((await request.get(textUrl)).status()).toBe(200);
});
