import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";
import { infoQuery } from "@/app/info";
import { CardsOnly } from "@/components/CardsOnly";
import { AutoResults } from "./AutoResults";
import { CardFilterPanel } from "./CardFilterPanel";
import { PagedResults } from "./PagedResults";
import { type PerPage, usePerPage } from "./perPage";
import { tileFields } from "./posts";
import { SearchBox } from "./SearchBox";
import { librarySearch } from "./search";

/**
 * The library: the search line, the card filters on a site with cards, and
 * the results, a page at a time or loaded as they are scrolled to.
 */
export function Library() {
  const { q = "", at = 0 } = useSearch({ from: "/posts" });
  const navigate = useNavigate();
  const [perPage, setPerPage] = usePerPage();
  const info = useQuery(infoQuery);

  // what is typed but not searched for yet; a new search in the URL replaces it
  const [draft, setDraft] = useState(q);
  const [searched, setSearched] = useState(q);
  if (q !== searched) {
    setSearched(q);
    setDraft(q);
  }

  // a new search is a new page of history, from the start
  const search = (query: string) => {
    navigate({ to: "/posts", search: librarySearch(query) });
  };

  // a change of mode keeps the place: page mode moves it to its page start
  const choose = (next: PerPage) => setPerPage(next);

  // the fields depend on the modules: the list waits for the site to say
  const known = info.isSuccess || info.isError;
  const fields = tileFields(info.data?.modules?.includes("cards") ?? false);

  return (
    <main className="mx-auto flex max-w-[1360px] flex-col gap-5 px-4 py-6 sm:px-8">
      <h1 className="sr-only">Library</h1>
      <SearchBox value={draft} onChange={setDraft} onSubmit={() => search(draft)} />
      <div className="flex flex-wrap items-start gap-7">
        <CardsOnly>
          <CardFilterPanel query={draft} onChange={search} />
        </CardsOnly>
        <section
          aria-label="Results"
          className="flex min-w-0 flex-[999_1_560px] flex-col gap-4"
        >
          {known ? (
            perPage === "auto" ? (
              <AutoResults
                key={`${q}\n${fields}`}
                q={q}
                at={at}
                fields={fields}
                onPerPage={choose}
              />
            ) : (
              <PagedResults
                q={q}
                at={at}
                size={perPage}
                fields={fields}
                onPerPage={choose}
              />
            )
          ) : null}
        </section>
      </div>
    </main>
  );
}
