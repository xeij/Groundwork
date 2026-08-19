import { useEffect, useRef, useState } from "react";
import { searchCompanies } from "../api/client";
import type { CompanySearchResult } from "../types";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 200;
const MIN_QUERY_LENGTH = 1;

interface Props {
  onSelect: (company: CompanySearchResult) => void;
  selected: CompanySearchResult | null;
  disabled?: boolean;
}

export function TickerSearch({ onSelect, selected, disabled }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CompanySearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Each keystroke supersedes the one before it: the cleanup cancels the pending timer,
  // and the generation check drops a response that arrives after a newer query was typed.
  const generationRef = useRef(0);

  useEffect(() => {
    if (query.trim().length < MIN_QUERY_LENGTH) {
      setResults([]);
      return;
    }
    const generation = ++generationRef.current;
    const timer = setTimeout(async () => {
      try {
        const found = await searchCompanies(query.trim());
        if (generationRef.current === generation) {
          setResults(found);
          setActiveIndex(0);
          setOpen(true);
        }
      } catch {
        if (generationRef.current === generation) setResults([]);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  function choose(company: CompanySearchResult) {
    onSelect(company);
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[activeIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <label htmlFor="ticker-search" className="mb-1.5 block text-sm font-medium text-foreground">
        Company ticker
      </label>
      <input
        id="ticker-search"
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls="ticker-results"
        aria-autocomplete="list"
        autoComplete="off"
        disabled={disabled}
        placeholder="AAPL, or search by company name"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => results.length > 0 && setOpen(true)}
        className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none disabled:opacity-50"
      />

      {selected && (
        <p className="mt-2 text-sm text-muted-foreground">
          Selected <span className="font-semibold text-foreground">{selected.ticker}</span> &middot;{" "}
          {selected.name}
        </p>
      )}

      {open && results.length > 0 && (
        <ul
          id="ticker-results"
          role="listbox"
          className="absolute z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-border bg-popover py-1 shadow-lg"
        >
          {results.map((company, i) => (
            <li key={`${company.cik}-${company.ticker}`}>
              <button
                type="button"
                role="option"
                aria-selected={i === activeIndex}
                onMouseEnter={() => setActiveIndex(i)}
                onClick={() => choose(company)}
                className={cn(
                  "flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-sm",
                  i === activeIndex ? "bg-secondary text-secondary-foreground" : "text-foreground",
                )}
              >
                <span className="w-16 shrink-0 font-semibold">{company.ticker}</span>
                <span className="truncate text-muted-foreground">{company.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
