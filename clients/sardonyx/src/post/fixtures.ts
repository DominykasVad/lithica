/** A post and the site's tag categories, as the tests' site answers them. */

export const POST = {
  id: 5,
  type: "image",
  mimeType: "image/png",
  safety: "sketchy",
  source: "https://example.com/art/5\nBook of the coast, page 3\njavascript:alert(1)",
  fileSize: 1_532_274,
  canvasWidth: 800,
  canvasHeight: 1200,
  contentUrl: "data/posts/5_abc.png",
  thumbnailUrl: "data/generated-thumbnails/5_abc.jpg",
  tags: [
    { names: ["mira_vell", "mira"], category: "character", usages: 3 },
    { names: ["coastal"], category: "default", usages: 120 },
    { names: ["a:b"], category: "default", usages: 1 },
  ],
  user: { name: "ashwyn", avatarUrl: "" },
  creationTime: "2026-10-20T14:30:00Z",
  lastEditTime: "2026-10-21T09:05:00Z",
  card: null,
};

export const CATEGORIES = {
  results: [
    { name: "character", color: "#aa3366", order: 2, usages: 1, default: false },
    { name: "default", color: "default", order: 1, usages: 9, default: true },
  ],
};
