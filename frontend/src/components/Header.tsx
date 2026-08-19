import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function Header({ right }: { right?: ReactNode }) {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
      <div className="mx-auto flex max-w-2xl items-center justify-between gap-4 px-5 py-3.5">
        <Link to="/" className="text-sm font-semibold tracking-tight text-foreground no-underline">
          Groundwork
        </Link>
        {right}
      </div>
    </header>
  );
}
