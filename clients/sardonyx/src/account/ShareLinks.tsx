import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { api } from "@/api/client";
import { unwrap } from "@/api/errors";
import { usePrivileges } from "@/app/privileges";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { usePerPage } from "@/library/perPage";
import { BATCH } from "@/library/posts";
import { ShareLinkRow } from "@/post/ShareLinks";

export function AccountShareLinks({ user }: { user: string }) {
  const auth = useAuth();
  const can = usePrivileges();
  if (!auth.user || !can?.("shareLinks:list:self")) return null;
  return (
    <Card className="mt-6">
      <CardContent>
        <UserShareLinks key={user} user={user} />
      </CardContent>
    </Card>
  );
}

function UserShareLinks({ user }: { user: string }) {
  const [perPage] = usePerPage();
  // Use the library batch size when its preference is auto-loading.
  const size = perPage === "auto" ? BATCH : perPage;
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: ["share-links", "user", user, offset],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/user/{user_name}/share-links", {
          params: { path: { user_name: user }, query: { offset, limit: size } },
          signal,
        }),
      ),
  });
  return (
    <section aria-label="Share links" className="flex min-w-0 flex-col gap-3">
      <h2 className="font-semibold">Share links</h2>
      {list.isError ? <ApiErrorMessage error={list.error} /> : null}
      {list.isPending ? <p>Loading share links…</p> : null}
      {list.isSuccess && !list.data.results?.length ? <p>No share links.</p> : null}
      <ul aria-label="Your share links" className="flex flex-col gap-3">
        {list.data?.results?.map((link) => (
          <li key={link.id} className="flex min-w-0 flex-col gap-2">
            <Link
              to="/posts/$id"
              params={{ id: String(link.postId) }}
              className="text-link hover:underline"
            >
              Post {link.postId}
            </Link>
            <ul>
              <ShareLinkRow link={link} />
            </ul>
          </li>
        ))}
      </ul>
      <nav aria-label="Share link pages" className="flex gap-2">
        <Button
          variant="outline"
          disabled={offset === 0 || list.isFetching}
          onClick={() => setOffset(Math.max(0, offset - size))}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          disabled={
            !list.data || offset + size >= (list.data.total ?? 0) || list.isFetching
          }
          onClick={() => setOffset(offset + size)}
        >
          Next
        </Button>
      </nav>
    </section>
  );
}
