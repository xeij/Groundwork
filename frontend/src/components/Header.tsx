import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function Header({ right }: { right?: ReactNode }) {
  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        background: "rgba(8, 9, 11, 0.7)",
        backdropFilter: "blur(8px)",
        position: "sticky",
        top: 0,
        zIndex: 10,
      }}
    >
      <div
        style={{
          maxWidth: 720,
          margin: "0 auto",
          padding: "0.9rem 1.25rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
        }}
      >
        <Link to="/" style={{ display: "flex", alignItems: "center", gap: "0.55rem", textDecoration: "none" }}>
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <rect x="1" y="1" width="18" height="18" rx="4" stroke="var(--accent)" strokeWidth="1.4" />
            <path d="M6 13.5V8.2L10 5.6l4 2.6v5.3" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M8.4 13.5V10h3.2v3.5" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span
            style={{
              fontFamily: "var(--font-serif)",
              fontSize: "1.05rem",
              fontWeight: 600,
              color: "var(--text-primary)",
              letterSpacing: "0.01em",
            }}
          >
            Groundwork
          </span>
        </Link>
        {right}
      </div>
    </header>
  );
}
