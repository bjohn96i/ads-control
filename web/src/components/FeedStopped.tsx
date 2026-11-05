export type Stopped = { since: string | null } | null;

/** A Google feed that has stopped; without this the page would look like a quiet house. */
export function FeedStopped({ stopped, text }: { stopped: Stopped | undefined; text: string }) {
  if (!stopped) return null;
  const since = stopped.since
    ? ` since ${new Date(stopped.since).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" })}`
    : "";
  return (
    <p className="warn" role="status">
      {text}
      {since}. If it doesn't come back, sign in to Google again with adscontrol nest login.
    </p>
  );
}
