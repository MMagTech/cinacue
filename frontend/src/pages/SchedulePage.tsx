import { useEffect, useState } from "react";
import {
  getSchedule,
  getStatus,
  addScheduledMovie,
  updateScheduledMovie,
  deleteScheduledMovie,
  ScheduleDay,
  ApiError,
} from "../api";
import { searchPlex, PlexMovie } from "../plexApi";

function fmtTime(iso: string, tz: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    timeZone: tz,
  });
}

// datetime-local value (YYYY-MM-DDTHH:MM) as wall-clock in the channel tz.
function toChannelInput(iso: string, tz: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso));
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  const hh = g("hour") === "24" ? "00" : g("hour");
  return `${g("year")}-${g("month")}-${g("day")}T${hh}:${g("minute")}`;
}

function errText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "That time overlaps another scheduled movie.";
    if (err.status === 422) return err.message;
    if (err.status === 503) return "Plex is not configured.";
    return err.message;
  }
  return "Something went wrong.";
}

export default function SchedulePage() {
  const [days, setDays] = useState<ScheduleDay[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tz, setTz] = useState("UTC");
  const [error, setError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PlexMovie[]>([]);
  const [chosen, setChosen] = useState<PlexMovie | null>(null);
  const [startInput, setStartInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editInput, setEditInput] = useState("");

  const reload = async () => {
    const d = await getSchedule();
    setDays(d);
    setSelected((cur) => cur ?? (d.length ? d[0].date : null));
  };

  useEffect(() => {
    getStatus().then((s) => setTz(s.timezone)).catch(() => {});
    reload().catch(() => setError("Could not load schedule."));
  }, []);

  const day = days.find((d) => d.date === selected);

  const openAdd = () => {
    setAdding(true);
    setChosen(null);
    setResults([]);
    setQ("");
    setAddError(null);
    setStartInput(`${selected}T19:00`);
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
      await addScheduledMovie(chosen.rating_key, startInput);
      setAdding(false);
      await reload();
    } catch (err) {
      setAddError(errText(err));
    }
  };

  const saveEdit = async (id: number) => {
    setError(null);
    try {
      await updateScheduledMovie(id, editInput);
      setEditingId(null);
      await reload();
    } catch (err) {
      setError(errText(err));
    }
  };

  const moveToDay = async (id: number, startIso: string, newDate: string) => {
    setError(null);
    const time = toChannelInput(startIso, tz).split("T")[1];
    try {
      await updateScheduledMovie(id, `${newDate}T${time}`);
      await reload();
    } catch (err) {
      setError(errText(err));
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this scheduled movie?")) return;
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
      <div className="days">
        {days.map((d) => {
          const dt = new Date(d.date + "T00:00:00");
          return (
            <button
              key={d.date}
              className={`day ${d.date === selected ? "active" : ""}`}
              onClick={() => setSelected(d.date)}
            >
              {dt.toLocaleDateString([], { weekday: "short" })}
              <small>
                {dt.toLocaleDateString([], { month: "short", day: "numeric" })}
              </small>
            </button>
          );
        })}
      </div>

      {error && <div className="error">{error}</div>}

      {day && (
        <div className="panel">
          <div className="topbar" style={{ marginBottom: 8 }}>
            <strong>{day.label}</strong>
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
                  <label>Start time (channel time, {tz})</label>
                  <input
                    type="datetime-local"
                    value={startInput}
                    onChange={(e) => setStartInput(e.target.value)}
                  />
                  <div style={{ marginTop: 12 }}>
                    <button className="btn" onClick={saveAdd} disabled={!chosen}>
                      Add “{chosen.title}”
                    </button>
                  </div>
                </div>
              )}

              {addError && <div className="error">{addError}</div>}
            </div>
          )}

          {day.movies.length === 0 ? (
            <div className="empty">No movies scheduled for this day.</div>
          ) : (
            day.movies.map((m) => (
              <div className="slot" key={m.id}>
                <div style={{ flex: 1 }}>
                  <div>
                    <strong>{m.title}</strong>
                    {m.year ? ` (${m.year})` : ""}
                  </div>
                  <div className="now-meta">
                    {fmtTime(m.scheduled_start, tz)} – {fmtTime(m.scheduled_end, tz)}
                  </div>

                  {editingId === m.id && (
                    <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                      <input
                        type="datetime-local"
                        value={editInput}
                        onChange={(e) => setEditInput(e.target.value)}
                        style={{ maxWidth: 240 }}
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
                      setEditInput(toChannelInput(m.scheduled_start, tz));
                    }}
                  >
                    Edit Time
                  </button>
                  <select
                    className="choice"
                    value={selected ?? ""}
                    onChange={(e) => moveToDay(m.id, m.scheduled_start, e.target.value)}
                    title="Move to another day"
                  >
                    {days.map((d) => (
                      <option key={d.date} value={d.date}>
                        Move → {new Date(d.date + "T00:00:00").toLocaleDateString([], {
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                        })}
                      </option>
                    ))}
                  </select>
                  <button className="choice" onClick={() => remove(m.id)}>
                    Delete
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      <div className="note">
        Overlapping movies are rejected — resolve the conflict and try again.
        Times are the channel's configured timezone ({tz}); gaps between movies
        are allowed and are never auto-filled.
      </div>
    </div>
  );
}
