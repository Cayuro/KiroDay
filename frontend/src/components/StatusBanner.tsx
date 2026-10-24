// Small inline status/alert banner with an ARIA live region so screen readers
// announce loading, success, and error states.

interface StatusBannerProps {
  kind: "info" | "success" | "error";
  message: string;
}

export function StatusBanner({ kind, message }: StatusBannerProps) {
  return (
    <div
      className={`banner banner-${kind}`}
      role={kind === "error" ? "alert" : "status"}
      aria-live={kind === "error" ? "assertive" : "polite"}
    >
      {message}
    </div>
  );
}
