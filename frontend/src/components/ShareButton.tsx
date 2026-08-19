import { useState } from "react";

export function ShareButton() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      onClick={copy}
      className={copied ? "btn" : "btn btn-primary"}
      style={
        copied
          ? {
              background: "var(--green-wash)",
              color: "var(--green)",
              borderColor: "var(--green-border)",
              padding: "0.6rem 1.25rem",
            }
          : { padding: "0.6rem 1.25rem" }
      }
    >
      {copied ? "Link copied!" : "Copy shareable link"}
    </button>
  );
}
