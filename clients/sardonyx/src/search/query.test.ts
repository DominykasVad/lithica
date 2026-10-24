import { describe, expect, it } from "vitest";
import { countFilters, readFilters, writeFilter } from "./cardFilters";
import { completing, suggestionQuery, take } from "./completion";
import { escapeValue, parts, unescapeValue } from "./query";

describe("escaping", () => {
  it("escapes what the engine treats specially, and only that", () => {
    expect(escapeValue("a:b")).toBe("a\\:b");
    expect(escapeValue("star*")).toBe("star\\*");
    expect(escapeValue("a,b")).toBe("a\\,b");
    expect(escapeValue("back\\slash")).toBe("back\\\\slash");
    expect(escapeValue("a..b")).toBe("a\\.\\.b");
    expect(escapeValue("-leading")).toBe("\\-leading");
    // a single dot and an inner dash mean nothing to the parser
    expect(escapeValue("v1.5")).toBe("v1.5");
    expect(escapeValue("sci-fi")).toBe("sci-fi");
  });

  it("comes back as it was", () => {
    for (const text of ["a:b", "x*y", "a,b", "c\\d", "a...b", "-x", "plain"]) {
      expect(unescapeValue(escapeValue(text))).toBe(text);
    }
  });

  it("reads keys and negation as the engine does", () => {
    expect(parts("-card-spec:v2")).toEqual({
      negated: true,
      key: "card-spec",
      value: "v2",
    });
    expect(parts("a\\:b")).toEqual({ negated: false, key: null, value: "a\\:b" });
    expect(parts("Sort:ID")).toMatchObject({ key: "sort", value: "ID" });
  });
});

describe("card filters in the query text", () => {
  it("reads every control", () => {
    expect(
      readFilters(
        "card-creator:ash*wyn card-spec:v2,v3 card-format:charx card-lorebook:yes card-greetings:2..",
      ),
    ).toEqual({
      creator: { state: "set", value: "ash wyn" },
      spec: { state: "set", value: ["v2", "v3"] },
      format: { state: "set", value: ["charx"] },
      lorebook: { state: "set", value: "yes" },
      greetings: { state: "set", value: 2 },
    });
    expect(readFilters("")).toEqual({
      creator: { state: "none" },
      spec: { state: "none" },
      format: { state: "none" },
      lorebook: { state: "none" },
      greetings: { state: "none" },
    });
  });

  it("round-trips: what is written reads back the same", () => {
    let query = "coastal -nsfw";
    query = writeFilter(query, "creator", "Ann Marie: the 2nd");
    query = writeFilter(query, "spec", ["v1", "v3"]);
    query = writeFilter(query, "format", ["png"]);
    query = writeFilter(query, "lorebook", "no");
    query = writeFilter(query, "greetings", 3);
    expect(query).toBe(
      "coastal -nsfw card-creator:Ann*Marie\\:*the*2nd card-spec:v1,v3 card-format:png card-lorebook:no card-greetings:3..",
    );
    expect(readFilters(query)).toEqual({
      creator: { state: "set", value: "Ann Marie: the 2nd" },
      spec: { state: "set", value: ["v1", "v3"] },
      format: { state: "set", value: ["png"] },
      lorebook: { state: "set", value: "no" },
      greetings: { state: "set", value: 3 },
    });
  });

  it("changes only its own token, in its place, and leaves the rest as typed", () => {
    const query = "Coastal  card-spec:v1 -nsfw\tsort:id";
    expect(writeFilter(query, "spec", ["v2"])).toBe(
      "Coastal  card-spec:v2 -nsfw\tsort:id",
    );
    expect(writeFilter(query, "spec", null)).toBe("Coastal -nsfw\tsort:id");
    expect(writeFilter(query, "format", ["charx"])).toBe(
      "Coastal  card-spec:v1 -nsfw\tsort:id card-format:charx",
    );
    expect(writeFilter("", "lorebook", "yes")).toBe("card-lorebook:yes");
  });

  it("writes no token for all or none, or for no greetings", () => {
    expect(writeFilter("x card-spec:v1", "spec", ["v1", "v2", "v3"])).toBe("x");
    expect(writeFilter("x card-spec:v1", "spec", [])).toBe("x");
    expect(writeFilter("card-format:png x", "format", ["png", "charx"])).toBe("x");
    expect(writeFilter("x card-greetings:2..", "greetings", 0)).toBe("x");
    expect(writeFilter("x card-creator:a", "creator", "  ")).toBe("x");
  });

  it("shows what it cannot write as custom, and keeps it until changed", () => {
    const query =
      "-card-spec:v1 card-greetings:2..4 card-lorebook:maybe card-creator:ash* card-format:png card-format:charx";
    expect(readFilters(query)).toEqual({
      creator: { state: "custom" },
      spec: { state: "custom" },
      format: { state: "custom" },
      lorebook: { state: "custom" },
      greetings: { state: "custom" },
    });
    // changing another control does not touch them
    expect(writeFilter(query, "lorebook", "yes")).toBe(
      "-card-spec:v1 card-greetings:2..4 card-lorebook:yes card-creator:ash* card-format:png card-format:charx",
    );
    // changing the control replaces all of its tokens
    expect(writeFilter(query, "format", ["png"])).toBe(
      "-card-spec:v1 card-greetings:2..4 card-lorebook:maybe card-creator:ash* card-format:png",
    );
    expect(readFilters("card-greetings-min:2").greetings).toEqual({ state: "custom" });
    expect(writeFilter("a card-greetings-min:2 b", "greetings", 5)).toBe(
      "a card-greetings:5.. b",
    );
  });

  it("escapes the creator as a tag name", () => {
    const query = writeFilter("", "creator", "a,b..c*");
    expect(query).toBe("card-creator:a\\,b\\.\\.c\\*");
    expect(readFilters(query).creator).toEqual({ state: "set", value: "a,b..c*" });
  });

  it("counts the controls that filter, custom ones too", () => {
    expect(countFilters("sea -nsfw")).toBe(0);
    expect(countFilters("card-spec:v2 card-format:png card-format:charx")).toBe(2);
    expect(countFilters("card-greetings-min:2 card-lorebook:yes")).toBe(2);
  });

  it("reads other spellings the engine takes", () => {
    expect(readFilters("CARD-SPEC:V2").spec).toEqual({ state: "set", value: ["v2"] });
    expect(readFilters("card-lorebook:false").lorebook).toEqual({
      state: "set",
      value: "no",
    });
  });
});

describe("completion", () => {
  it("completes the token under the cursor", () => {
    expect(completing("coast", 5)).toMatchObject({ prefix: "coast", negated: false });
    expect(completing("a coast b", 4)).toMatchObject({ prefix: "coast" });
    expect(completing("-nsf", 4)).toMatchObject({ prefix: "nsf", negated: true });
  });

  it("skips named tokens, a lone dash and whitespace", () => {
    expect(completing("card-spec:v2", 12)).toBeNull();
    expect(completing("sort:id", 3)).toBeNull();
    expect(completing("-", 1)).toBeNull();
    expect(completing("a  b", 2)).toBeNull();
  });

  it("asks for the most used tags that start with the prefix", () => {
    expect(suggestionQuery("coa")).toBe("coa* sort:usages");
  });

  it("replaces only that token, escaped, keeping the dash", () => {
    const query = "sea -nsf sort:id";
    const target = completing(query, 8);
    expect(target).not.toBeNull();
    expect(take(query, target as NonNullable<typeof target>, "nsfw:art")).toEqual({
      query: "sea -nsfw\\:art sort:id",
      cursor: 15,
    });
    const atEnd = completing("sea coa", 7);
    expect(take("sea coa", atEnd as NonNullable<typeof atEnd>, "coastal")).toEqual({
      query: "sea coastal ",
      cursor: 12,
    });
  });
});
