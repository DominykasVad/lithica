import { useQuery } from "@tanstack/react-query";
import {
  Link,
  Navigate,
  Outlet,
  useLocation,
  useNavigate,
} from "@tanstack/react-router";
import {
  LogIn,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Palette,
  Settings,
  Sun,
  UserRound,
} from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/errors";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { CardsOnly } from "@/components/CardsOnly";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { infoQuery } from "./info";
import { Login } from "./Login";
import { useShowNsfw } from "./nsfw";
import { useCanUpload, usePrivileges } from "./privileges";
import { type Theme, useTheme } from "./theme";

/** How this browser shows the site: the theme, and whether NSFW posts are shown. */
function DisplayMenu() {
  const { theme, setTheme } = useTheme();
  const [showNsfw, setShowNsfw] = useShowNsfw();
  const Icon =
    theme === "dark"
      ? Moon
      : theme === "dracula"
        ? Palette
        : theme === "light"
          ? Sun
          : Monitor;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Display" className="shrink-0">
          <Icon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={theme}
          onValueChange={(value) => setTheme(value as Theme)}
        >
          <DropdownMenuRadioItem value="light">Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">Dark</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dracula">Dracula</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">As the system</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem
          checked={showNsfw}
          onCheckedChange={(checked) => setShowNsfw(checked === true)}
        >
          Show NSFW
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [failed, setFailed] = useState<unknown>(null);

  const logOut = async () => {
    setFailed(await auth.logOut());
    navigate({ to: "/" });
  };
  return (
    <>
      {auth.user ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            {/* the one part of the header that gives way: a long name is cut short */}
            <Button variant="ghost" size="sm" className="min-w-0 shrink">
              <UserRound />
              <span className="min-w-0 max-w-48 truncate">{auth.user}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Logged in as {auth.user}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/account">
                <Settings />
                Account
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={logOut}>
              <LogOut />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <Button asChild variant="outline" size="sm">
          <Link to="/login">
            <LogIn />
            Log in
          </Link>
        </Button>
      )}
      {failed ? (
        // logged out here although the site could not be told: it says why
        <div className="fixed right-4 bottom-4 flex max-w-sm flex-col items-end gap-2">
          <ApiErrorMessage error={failed} />
          <Button variant="outline" size="sm" onClick={() => setFailed(null)}>
            Close
          </Button>
        </div>
      ) : null}
    </>
  );
}

/** Upload, for those who may: the link is not there for anyone else. */
function UploadLink() {
  return useCanUpload() ? (
    <Button asChild variant="ghost" size="sm" className="max-sm:hidden">
      <Link to="/upload" activeProps={{ "aria-current": "page" }}>
        Upload
      </Link>
    </Button>
  ) : null;
}

/** The tags page, for those who may list the tags. */
function useCanListTags(): boolean {
  return usePrivileges()?.("tags:list") ?? false;
}

function TagsLink() {
  return useCanListTags() ? (
    <Button asChild variant="ghost" size="sm" className="max-sm:hidden">
      <Link to="/tags" activeProps={{ "aria-current": "page" }}>
        Tags
      </Link>
    </Button>
  ) : null;
}

/** The pages of the navigation, folded into one button on a phone. */
function NavMenu() {
  const canUpload = useCanUpload();
  const canListTags = useCanListTags();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Menu"
          className="shrink-0 sm:hidden"
        >
          <Menu />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem asChild>
          <Link to="/" activeOptions={{ exact: true }}>
            Home
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/posts">Library</Link>
        </DropdownMenuItem>
        {canListTags ? (
          <DropdownMenuItem asChild>
            <Link to="/tags">Tags</Link>
          </DropdownMenuItem>
        ) : null}
        {canUpload ? (
          <DropdownMenuItem asChild>
            <Link to="/upload">Upload</Link>
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const SESSION_ENDED = new ApiError(
  "SessionEnded",
  "You are logged out",
  "The site no longer accepts your login. Log in again to go on.",
  403,
);

/**
 * On a site that shows nothing without logging in (`visibility: login`),
 * whether this visitor is kept out: not logged in. Null while the site
 * has not said.
 */
function useLockedOut(): boolean | null {
  const auth = useAuth();
  const info = useQuery(infoQuery);
  // only until the site first answers: a page asking again after a failure
  // makes the query pending once more, and must not be taken off the page
  if (info.data === undefined && info.errorUpdateCount === 0) {
    return null;
  }
  // a site that did not answer is not taken for a closed one: its pages
  // say what fails
  return info.data?.visibility === "login" && !auth.user;
}

/**
 * What a visitor kept out gets in place of any page: the login form, at
 * /login, and back to the page they asked for once logged in. No page of
 * the app is drawn for them, not even for a moment while the address
 * changes, so none asks the site for anything.
 */
function LockedOut() {
  const location = useLocation();
  // resetting a password needs no login (the site allows it too)
  if (location.pathname.startsWith("/password-reset")) {
    return <Outlet />;
  }
  if (location.pathname !== "/login") {
    return <Navigate to="/login" search={{ redirect: location.href }} replace />;
  }
  const { redirect } = location.search as { redirect?: unknown };
  return <Login redirect={typeof redirect === "string" ? redirect : undefined} />;
}

/** Every page: the header with the name, the navigation and the user, then the page. */
export function Shell() {
  const auth = useAuth();
  const lockedOut = useLockedOut();
  // nothing of a page is drawn (or asked for) before the site has said
  // whether it is closed
  const page = lockedOut === null ? null : lockedOut ? <LockedOut /> : <Outlet />;
  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-2 sm:gap-4">
          <Link to="/" className="flex shrink-0 items-center gap-2 font-semibold">
            <Logo className="size-7" />
            Sardonyx
          </Link>
          {lockedOut ? (
            <span className="flex-1" />
          ) : (
            <nav aria-label="Main" className="flex flex-1 items-center gap-1 text-sm">
              <NavMenu />
              <Button asChild variant="ghost" size="sm" className="max-sm:hidden">
                <Link
                  to="/"
                  activeOptions={{ exact: true }}
                  activeProps={{ "aria-current": "page" }}
                >
                  Home
                </Link>
              </Button>
              <Button asChild variant="ghost" size="sm" className="max-sm:hidden">
                <Link to="/posts" activeProps={{ "aria-current": "page" }}>
                  Library
                </Link>
              </Button>
              <TagsLink />
              <UploadLink />
              <CardsOnly>
                <span className="rounded-full bg-accent px-2 max-sm:hidden py-0.5 text-accent-foreground text-xs">
                  Character cards
                </span>
              </CardsOnly>
            </nav>
          )}
          <DisplayMenu />
          {lockedOut ? null : <UserMenu />}
        </div>
      </header>
      {auth.ended && !auth.user ? (
        <div className="mx-auto max-w-5xl px-4 pt-4">
          <ApiErrorMessage error={SESSION_ENDED} />
        </div>
      ) : null}
      {page}
    </div>
  );
}

export function NotFound() {
  return (
    <main className="mx-auto max-w-5xl p-6">
      <h1 className="font-semibold text-xl">Not found</h1>
      <p className="text-muted-foreground">There is no page here.</p>
    </main>
  );
}
