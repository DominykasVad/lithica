import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import { LogIn, LogOut, Menu, Monitor, Moon, Sun, UserRound } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/errors";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { CardsOnly } from "@/components/CardsOnly";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { type Theme, useTheme } from "./theme";

function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Theme" className="shrink-0">
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
          <DropdownMenuRadioItem value="system">As the system</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
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

/** The pages of the navigation, folded into one button on a phone. */
function NavMenu() {
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

/** Every page: the header with the name, the navigation and the user, then the page. */
export function Shell() {
  const auth = useAuth();
  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-2 sm:gap-4">
          <Link to="/" className="flex shrink-0 items-center gap-2 font-semibold">
            <Logo className="size-7" />
            Sardonyx
          </Link>
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
            <CardsOnly>
              <span className="rounded-full bg-accent px-2 max-sm:hidden py-0.5 text-accent-foreground text-xs">
                Character cards
              </span>
            </CardsOnly>
          </nav>
          <ThemeMenu />
          <UserMenu />
        </div>
      </header>
      {auth.ended && !auth.user ? (
        <div className="mx-auto max-w-5xl px-4 pt-4">
          <ApiErrorMessage error={SESSION_ENDED} />
        </div>
      ) : null}
      <Outlet />
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
