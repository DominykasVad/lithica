import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import { infoQuery, useHasCards } from "@/app/info";
import { lowestRank, usePrivileges } from "@/app/privileges";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Paging } from "@/library/Paging";
import { categoriesQuery } from "@/post/queries";
import { CompletionInput } from "@/search/CompletionInput";
import { escapeValue } from "@/search/query";
import {
  CREATOR_CATEGORY,
  CREATOR_COLOR,
  hasCategory,
  inOrder,
  swatch,
  type TagCategory,
} from "./categories";
import { tagQuery, tagsSearch } from "./search";

/** Tags on a page. */
export const PAGE_SIZE = 50;
export const LIST_PRIVILEGE = "tags:list";
// as GET /info names it: the site writes privilege names in camelCase
export const CREATE_CATEGORY_PRIVILEGE = "tagCategories:create";

function NotAllowed() {
  const { user } = useAuth();
  const info = useQuery(infoQuery);
  const rank = lowestRank(info.data?.config?.privileges, [LIST_PRIVILEGE]);
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-3 px-4 py-6 sm:px-8">
      <h1 className="font-semibold font-serif text-3xl">Tags</h1>
      {user === null ? (
        <p>
          The list of tags is for members.{" "}
          <Link
            to="/login"
            search={{ redirect: "/tags" }}
            className="text-link underline"
          >
            Log in
          </Link>{" "}
          to see it.
        </p>
      ) : (
        <p>
          Your account cannot list the tags of this site
          {rank && rank !== "nobody" ? `: that takes the rank ${rank} or higher` : ""}.
        </p>
      )}
    </main>
  );
}

/**
 * The cards module files a card's creator under the `creator` category;
 * a site without it puts creators in the default one. Offered to whoever
 * may create categories, on a site with cards, while it is missing.
 */
function CreatorCategoryOffer({ categories }: { categories: TagCategory[] }) {
  const client = useQueryClient();
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tag-categories", {
          body: {
            name: CREATOR_CATEGORY,
            color: CREATOR_COLOR,
            order:
              Math.max(0, ...categories.map((category) => category.order ?? 0)) + 1,
          },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: categoriesQuery.queryKey }),
  });
  return (
    <section
      aria-label="The creator category"
      className="flex flex-col items-start gap-3 rounded-2xl border bg-card p-4"
    >
      <p className="text-sm">
        The cards module files each card's creator under the tag category{" "}
        <code className="font-mono">{CREATOR_CATEGORY}</code>. This site has no such
        category yet, so creators go into the default category. Once it exists, new
        creators go into it; creators already on the site stay where they are.
      </p>
      {create.isError ? <ApiErrorMessage error={create.error} /> : null}
      <Button onClick={() => create.mutate()} disabled={create.isPending}>
        Create the creator category
      </Button>
    </section>
  );
}

function CategoryFilter({
  q,
  current,
  categories,
}: {
  q: string;
  current: string | undefined;
  categories: TagCategory[];
}) {
  const chip =
    "inline-flex items-center gap-1.5 rounded-full border border-control-border px-3 py-1 text-sm hover:bg-accent hover:text-accent-foreground";
  const active =
    "border-primary bg-primary text-primary-foreground hover:bg-primary/90";
  return (
    <nav aria-label="Categories" className="flex flex-wrap gap-1.5">
      <Link
        to="/tags"
        search={tagsSearch(q, undefined)}
        aria-current={current === undefined ? "page" : undefined}
        className={cn(chip, current === undefined && active)}
      >
        All
      </Link>
      {categories.map((category) => {
        const name = category.name ?? "";
        const color = swatch(category.color);
        return (
          <Link
            key={name}
            to="/tags"
            search={tagsSearch(q, name)}
            aria-current={current === name ? "page" : undefined}
            className={cn(chip, current === name && active)}
          >
            {color ? (
              <span
                aria-hidden
                data-color={color}
                className="size-2.5 rounded-full border"
                style={{ backgroundColor: color }}
              />
            ) : null}
            {name}
          </Link>
        );
      })}
    </nav>
  );
}

function TagList() {
  const id = useId();
  const navigate = useNavigate();
  const { q = "", category, at = 0 } = useSearch({ from: "/tags" });
  const [text, setText] = useState(q);
  useEffect(() => setText(q), [q]);
  const can = usePrivileges();
  const hasCards = useHasCards();
  const categories = useQuery(categoriesQuery);
  const ordered = inOrder(categories.data?.results);
  const offset = Math.floor(at / PAGE_SIZE) * PAGE_SIZE;
  const page = useQuery({
    queryKey: ["tags", "page", q, category, offset],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/tags", {
          params: {
            query: {
              query: tagQuery(q, category),
              offset,
              limit: PAGE_SIZE,
              fields: "names,category,usages",
            },
          },
          signal,
        }),
      ),
  });
  const total = page.data?.total ?? null;
  const results = page.data?.results ?? [];
  const colorOf = (name: string | undefined) =>
    swatch(ordered.find((one) => one.name === name)?.color);

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-6 sm:px-8">
      <h1 className="font-semibold font-serif text-3xl">Tags</h1>
      {hasCards &&
      categories.isSuccess &&
      !hasCategory(categories.data.results, CREATOR_CATEGORY) &&
      can?.(CREATE_CATEGORY_PRIVILEGE) ? (
        <CreatorCategoryOffer categories={ordered} />
      ) : null}
      {/* biome-ignore lint/a11y/useSemanticElements: a form, so that Enter searches; role says it is the search */}
      <form
        role="search"
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          navigate({ to: "/tags", search: tagsSearch(text, category) });
        }}
      >
        <label htmlFor={`${id}-q`} className="sr-only">
          Search tags
        </label>
        <CompletionInput
          id={`${id}-q`}
          value={text}
          onChange={setText}
          placeholder="e.g. fantasy* or usages:10.."
          className="flex-1"
          inputClassName="h-11"
        />
        <Button type="submit" className="h-11">
          <Search />
          Search
        </Button>
      </form>
      {ordered.length ? (
        <CategoryFilter q={q} current={category} categories={ordered} />
      ) : null}
      {page.isError ? <ApiErrorMessage error={page.error} /> : null}
      <p className="text-muted-foreground text-sm" aria-live="polite">
        {total === null ? "Loading tags…" : `${total} tag${total === 1 ? "" : "s"}`}
      </p>
      {results.length ? (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground text-xs">
              <th scope="col" className="py-2 font-medium">
                Tag
              </th>
              <th scope="col" className="py-2 font-medium">
                Category
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Posts
              </th>
            </tr>
          </thead>
          <tbody>
            {results.map((tag) => {
              const name = tag.names?.[0] ?? "";
              const color = colorOf(tag.category);
              return (
                <tr key={name} className="border-b last:border-b-0">
                  <td className="py-2 pr-3">
                    <Link
                      to="/posts"
                      search={{ q: escapeValue(name) }}
                      className="break-all font-mono text-link underline-offset-4 hover:underline"
                    >
                      {name}
                    </Link>
                  </td>
                  <td className="py-2 pr-3">
                    <span className="inline-flex items-center gap-1.5">
                      {color ? (
                        <span
                          aria-hidden
                          data-color={color}
                          className="size-2.5 rounded-full border"
                          style={{ backgroundColor: color }}
                        />
                      ) : null}
                      {tag.category}
                    </span>
                  </td>
                  <td className="py-2 text-right tabular-nums">{tag.usages}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : page.isSuccess ? (
        <p>No tags match.</p>
      ) : null}
      {total ? (
        <Paging
          list={{ to: "/tags", searchAt: (next) => tagsSearch(q, category, next) }}
          page={offset / PAGE_SIZE}
          size={PAGE_SIZE}
          total={total}
        />
      ) : null}
    </main>
  );
}

/** `/tags`: the site's tags, searched, by category, a page at a time. */
export function TagsPage() {
  const can = usePrivileges();
  if (can === null) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-8">
        <p className="text-muted-foreground">Loading…</p>
      </main>
    );
  }
  return can(LIST_PRIVILEGE) ? <TagList /> : <NotAllowed />;
}
