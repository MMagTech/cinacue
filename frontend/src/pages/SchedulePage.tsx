import { useEffect, useState } from "react";
import {
  getSchedule,
  addScheduledMovie,
  updateScheduledMovie,
  deleteScheduledMovie,
  setActiveDays,
  ScheduledMovie,
  ApiError,
} from "../api";
import { searchPlex, PlexMovie } from "../plexApi";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// minutes-from-midnight -> "8:00 PM"
function fmtTime(min: number): string {
  const t = ((min % 1440) + 1440) % 1440;
  let h = Math.floor(t / 60);
  const m = t % 60;
  const ampm = h < 12 ? "AM" : "PM";
  h = h % 12;
  if (h === 0) h = 12;
  return `${h}:${String(m).padStart(2, "0")} ${ampm}`;
}

// minutes -> "HH:MM" for a <input type="time">
function toInput(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// "HH:MM" -> minutes
function fromInput(v: string): number {
  const [h, m] = v.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}

function endLabel(m: ScheduledMovie): string {
  const end = m.start_minute + Math.round(m.runtime_ms / 60000);
  return fmtTime(end) + (end >= 1440 ? " (next day)" : "");
}

function errText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "That time overlaps another movie in the lineup.";
    if (err.status === 422) return err.message;
    if (err.status === 503) return "Plex is not configured.";
    return err.message;
  }
  return "Something went wrong.";
}

export default function SchedulePage() {
  const [movies, setMovies] = useState<ScheduledMovie[]>([]);
  const [activeDays, setActiveDaysState] = useState<number[]>([]);
  const [tz, setTz] = useState("UTC");
  const [error, setError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PlexMovie[]>([]);
  const [chosen, setChosen] = useState<PlexMovie | null>(null);
  const [startInput, setStartInput] = useState("20:00");
  const [addError, setAddError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editInput, setEditInput] = useState("20:00");

  const reload = async () => {
    const r = await getSchedule();
    setMovies(r.movies);
    setActiveDaysState(r.active_days);
    setTz(r.timezone);
  };

  useEffect(() => {
    reload().catch(() => setError("Could not load schedule."));
  }, []);

  const toggleDay = async (d: number) => {
    setError(null);
    const next = activeDays.includes(d)
      ? activeDays.filter((x) => x !== d)
      : [...activeDays, d].sort((a, b) => a - b);
    try {
      const r = await setActiveDays(next);
      setActiveDaysState(r.active_days);
    } catch (err) {
      setError(errText(err));
    }
  };

  const openAdd = () => {
    setAdding(true);
    setChosen(null);
    setResults([]);
    setQ("");
    setAddError(null);
    setStartInput("20:00");
  };

  const runSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setSearching(true);
    setAddError(null);
    try {
      setResults(await searchPlex(q.trim()));
    } catch (err) {
      setAddError(errText(err));
    } finally {
      setSearching(false);
    }
  };

  const saveAdd = async () => {
    if (!chosen) return;
    setAddError(null);
    try {
      await addScheduledMovie(chosen.rating_key, fromInput(startInput));
      setAdding(false);
      await reload();
    } catch (err) {
      setAddError(errText(err));
    }
  };

  const saveEdit = async (id: number) => {
    setError(null);
    try {
      await updateScheduledMovie(id, fromInput(editInput));
      setEditingId(null);
      await reload();
    } catch (err) {
      setError(errText(err));
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Remove this movie from the daily lineup?")) return;
    setError(null);
    try {
      await deleteScheduledMovie(id);
      await reload();
    } catch (err) {
      setError(errText(err));
    }
  };

  return (
    <div>
      <div className="panel" style={{ marginBottom: 16 }}>
        <strong>On-air days</strong>
        <div className="now-meta" style={{ margin: "4px 0 10px" }}>
          Days that are off show nothing — the channel goes off air.
        </div>
        <div className="days">
          {WEEKDAYS.map((label, d) => (
            <button
              key={d}
              className={`day ${activeDays.includes(d) ? "active" : ""}`}
              onClick={() => toggleDay(d)}
              title={activeDays.includes(d) ? "On air — click to turn off" : "Off air — click to turn on"}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="panel">
        <div className="topbar" style={{ marginBottom: 8 }}>
          <strong>Daily lineup ({tz})</strong>
          {!adding && (
            <button className="btn" onClick={openAdd}>
              + Add Movie
            </button>
          )}
        </div>

        {adding && (
          <div className="panel" style={{ marginBottom: 16 }}>
            <form onSubmit={runSearch}>
              <label>Search the Plex library</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="e.g. Ghostbusters"
                  autoFocus
                />
                <button className="btn" type="submit" disabled={searching || !q.trim()}>
                  {searching ? "…" : "Search"}
                </button>
                <button
                  type="button"
                  className="btn secondary"
                  onClick={() => setAdding(false)}
                >
                  Cancel
                </button>
              </div>
            </form>

            <div style={{ display: "grid", gap: 8, margin: "12px 0" }}>
              {results.map((m) => (
                <div
                  key={m.rating_key}
                  className="choice"
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    borderColor:
                      chosen?.rating_key === m.rating_key ? "var(--accent)" : undefined,
                  }}
                  onClick={() => setChosen(m)}
                >
                  <span>
                    {m.title}
                    {m.year ? ` (${m.year})` : ""}
                  </span>
                  <span className="now-meta">
                    {m.runtime_minutes} min
                    {m.source_available ? "" : " · file missing"}
                  </span>
                </div>
              ))}
            </div>

            {chosen && (
              <div>
                <label>Daily start time (channel time, {tz})</label>
                <input
                  type="time"
                  value={startInput}
                  onChange={(e) => setStartInput(e.target.value)}
                />
                {!chosen.source_available && (
                  <div className="error" style={{ marginTop: 8 }}>
                    Source file not found on the mount — check the movie path
                    mapping before scheduling this title.
                  </div>
                )}
                <div style={{ marginTop: 12 }}>
                  <button
                    className="btn"
                    onClick={saveAdd}
                    disabled={!chosen.source_available}
                    title={
                      chosen.source_available
                        ? "Add to the daily lineup"
                        : "The source file must be reachable first"
                    }
                  >
                    Add “{chosen.title}”
                  </button>
                </div>
              </div>
            )}

            {addError && <div className="error">{addError}</div>}
          </div>
        )}

        {movies.length === 0 ? (
          <div className="empty">No movies in the daily lineup yet.</div>
        ) : (
          movies.map((m) => (
            <div className="slot" key={m.id}>
              <div style={{ flex: 1 }}>
                <div>
                  <strong>{m.title}</strong>
                  {m.year ? ` (${m.year})` : ""}
                </div>
                <div className="now-meta">
                  {fmtTime(m.start_minute)} – {endLabel(m)}
                </div>

                {editingId === m.id && (
                  <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                    <input
                      type="time"
                      value={editInput}
                      onChange={(e) => setEditInput(e.target.value)}
                      style={{ maxWidth: 160 }}
                    />
                    <button className="btn" onClick={() => saveEdit(m.id)}>
                      Save
                    </button>
                    <button
                      className="btn secondary"
                      onClick={() => setEditingId(null)}
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>

              <div className="pill-row">
                <button
                  className="choice"
                  onClick={() => {
                    setEditingId(m.id);
                    setEditInput(toInput(m.start_minute));
                  }}
                >
                  Edit Time
                </button>
                <button className="choice" onClick={() => remove(m.id)}>
                  Delete
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="note">
        The lineup repeats every on-air day. Overlapping movies are rejected —
        a movie that starts late may run past midnight. Times are the channel's
        configured timezone ({tz}).
      </div>
    </div>
  );
}
