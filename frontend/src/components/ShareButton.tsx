import { useState } from "react";
import { Button } from "./ui/button";

export function ShareButton() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Button onClick={copy} variant={copied ? "secondary" : "default"}>
      {copied ? "Link copied" : "Copy shareable link"}
    </Button>
  );
}
