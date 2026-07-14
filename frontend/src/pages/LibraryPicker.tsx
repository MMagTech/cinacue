import { useEffect, useState } from "react";
import { getPlexStatus, searchPlex, PlexStatus, PlexMovie } from "../plexApi";
import { addScheduledMovie, ApiError } from "../api";

// Milestone 2/3 Plex library picker: search the movie library, inspect results,
// and add a movie to the schedule inline (pick a start time, backend computes
// the end time and rejects overlaps).
export default function LibraryPicker() {
  const [status, setStatus] = useState<PlexStatus | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PlexMovie[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);

  // Inline add state, keyed by rating_key.
  const [addKey, setAddKey] = useState<string | null>(null);
  const [startInput, setStartInput] = useState("");
  const [addMsg, setAddMsg] = useState<{ key: string; text: string; ok: boolean } | null>(
    null
  );

  useEffect(() => {
    getPlexStatus()
      .then(setStatus)
      .catch(() => setError("Could not check Plex status."));
  }, []);

  const runSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResults(await searchPlex(q.trim()));
      setSearched(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError("Plex is not configured. Set PLEX_URL and PLEX_TOKEN.");
      } else if (err instanceof ApiError && err.status === 502) {
        setError("Could not reach Plex. Check the server URL and token.");
      } else {
        setError("Search failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  const openAdd = (m: PlexMovie) => {
    setAddKey(m.rating_key);
    setAddMsg(null);
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    setStartInput(
      `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T20:00`
    );
  };

  const confirmAdd = async (m: PlexMovie) => {
    try {
      await addScheduledMovie(m.rating_key, startInput);
      setAddMsg({ key: m.rating_key, text: "Added to schedule.", ok: true });
      setAddKey(null);
    } catch (err) {
      let text = "Could not add.";
      if (err instanceof ApiError) {
        if (err.status === 409) text = "That time overlaps another movie.";
        else if (err.status === 422) text = err.message;
        else if (err.status === 503) text = "Plex is not configured.";
      }
      setAddMsg({ key: m.rating_key, text, ok: false });
    }
  };

  const notReady =
    status && (!status.configured || !status.reachable || !status.library_found);

  return (
    <div>
      {status && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="pill-row" style={{ gap: 16 }}>
            <span>
              Configured:{" "}
              <strong style={{ color: status.configured ? "var(--ok)" : "var(--danger)" }}>
                {status.configured ? "yes" : "no"}
              </strong>
            </span>
            <span>
              Reachable:{" "}
              <strong style={{ color: status.reachable ? "var(--ok)" : "var(--danger)" }}>
                {status.reachable ? "yes" : "no"}
              </strong>
            </span>
            <span>
              Library “{status.library_name}”:{" "}
              <strong style={{ color: status.library_found ? "var(--ok)" : "var(--danger)" }}>
                {status.library_found ? "found" : "not found"}
              </strong>
            </span>
          </div>
        </div>
      )}

      {notReady && (
        <div className="note">
          Plex isn't fully connected yet. Set <code>PLEX_URL</code>,{" "}
          <code>PLEX_TOKEN</code>, and <code>PLEX_LIBRARY_NAME</code> in your
          environment and restart the container.
        </div>
      )}

      <form onSubmit={runSearch} style={{ margin: "16px 0" }}>
        <label htmlFor="q">Search the movie library</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            id="q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. Back to the Future"
          />
          <button className="btn" type="submit" disabled={busy || !q.trim()}>
            {busy ? "Searching…" : "Search"}
          </button>
        </div>
      </form>

      {error && <div className="error">{error}</div>}

      {searched && results.length === 0 && !error && (
        <div className="empty">No matching movies.</div>
      )}

      <div style={{ display: "grid", gap: 12 }}>
        {results.map((m) => (
          <div className="panel" key={m.rating_key} style={{ display: "flex", gap: 16 }}>
            {m.poster_url ? (
              <img
                className="poster"
                src={m.poster_url}
                alt={m.title}
                style={{ width: 92, flex: "0 0 auto" }}
              />
            ) : (
              <div className="poster" style={{ width: 92, flex: "0 0 auto" }} />
            )}
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>
                {m.title}
                {m.year ? ` (${m.year})` : ""}
              </div>
              <div className="now-meta">
                {m.runtime_minutes} min
                {m.source_resolution ? ` · ${m.source_resolution}` : ""}
                {m.video_codec ? ` · ${m.video_codec}` : ""}
                {m.container ? ` · ${m.container}` : ""}
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: m.source_available ? "var(--ok)" : "var(--danger)",
                  marginTop: 4,
                }}
              >
                {m.source_available
                  ? "Source file found on mount"
                  : "Source file NOT found — check path translation"}
              </div>

              {addKey === m.rating_key ? (
                <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <input
                    type="datetime-local"
                    value={startInput}
                    onChange={(e) => setStartInput(e.target.value)}
                    style={{ maxWidth: 220 }}
                  />
                  <button className="btn" onClick={() => confirmAdd(m)}>
                    Confirm
                  </button>
                  <button className="btn secondary" onClick={() => setAddKey(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div style={{ marginTop: 10 }}>
                  <button
                    className="btn secondary"
                    onClick={() => openAdd(m)}
                    disabled={!m.source_available}
                    title={
                      m.source_available
                        ? "Add to schedule"
                        : "Source file not found on the mount"
                    }
                  >
                    Add to schedule
                  </button>
                </div>
              )}

              {addMsg && addMsg.key === m.rating_key && (
                <div
                  style={{
                    marginTop: 8,
                    fontSize: 13,
                    color: addMsg.ok ? "var(--ok)" : "var(--danger)",
                  }}
                >
                  {addMsg.text}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="note">
        Adding here uses your computer's local date/time. The Schedule tab shows
        and edits times in the channel's configured timezone.
      </div>
    </div>
  );
}
