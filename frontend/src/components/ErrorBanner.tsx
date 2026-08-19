interface Props {
  message: string;
  onDismiss?: () => void;
}

export function ErrorBanner({ message, onDismiss }: Props) {
  return (
    <div
      role="alert"
      style={{
        background: "var(--red-wash)",
        border: "1px solid var(--red-border)",
        borderRadius: "var(--radius-sm)",
        padding: "0.75rem 0.9rem",
        color: "var(--red)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: "0.6rem",
        fontSize: "0.88rem",
        lineHeight: 1.5,
      }}
    >
      <span>{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss error"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--red)",
            fontWeight: 700,
            flexShrink: 0,
            opacity: 0.8,
          }}
        >
          &#x2715;
        </button>
      )}
    </div>
  );
}
