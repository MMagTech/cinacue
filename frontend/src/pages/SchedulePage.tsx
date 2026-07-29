import { Fragment, useEffect, useRef, useState } from "react";
import {
  getSchedule,
  addScheduledMovie,
  updateScheduledMovie,
  deleteScheduledMovie,
  clearSchedule,
  setActiveDays,
  ScheduledMovie,
  ApiError,
} from "../api";
import { searchPlex, PlexMovie } from "../plexApi";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function fmtTime(min: number): string {
  const t = ((min % 1440) + 1440) % 1440;
  let h = Math.floor(t / 60);
  const m = t % 60;
  const ampm = h < 12 ? "AM" : "PM";
  h = h % 12;
  if (h === 0) h = 12;
  return `${h}:${String(m).padStart(2, "0")} ${ampm}`;
}
function toInput(min: number): string {
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}
function fromInput(v: string): number {
  const [h, m] = v.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}
function endMinute(m: ScheduledMovie): number {
  return m.start_minute + Math.round(m.runtime_ms / 60000);
}
function endLabel(m: ScheduledMovie): string {
  const end = endMinute(m);
  return fmtTime(end) + (end >= 1440 ? " (next day)" : "");
}
function fmtDuration(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (!h) return `${m} min`;
  return m ? `${h} hr ${m} min` : `${h} hr`;
}

const EMPTY_LINEUP_START = 7 * 60 + 30; // 07:30 — first slot of a fresh day

/** Where the next movie most likely goes: the end of the lineup, rounded up
 * to the next quarter-hour (07:30 when the lineup is empty). */
function suggestedStart(movies: ScheduledMovie[]): number {
  if (movies.length === 0) return EMPTY_LINEUP_START;
  const end = Math.max(...movies.map(endMinute));
  return (Math.ceil(end / 15) * 15) % 1440;
}

/** Advisory only — the server is the real overlap authority. */
function findOverlap(
  start: number,
  runtimeMin: number,
  movies: ScheduledMovie[]
): ScheduledMovie | null {
  for (const m of movies) {
    if (start < endMinute(m) && m.start_minute < start + runtimeMin) return m;
  }
  return null;
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
  const [startInput, setStartInput] = useState(toInput(EMPTY_LINEUP_START));
  const [addError, setAddError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editInput, setEditInput] = useState(toInput(EMPTY_LINEUP_START));

  const reload = async () => {
    const r = await getSchedule();
    setMovies(r.movies);
    setActiveDaysState(r.active_days);
    setTz(r.timezone);
    return r;
  };

  useEffect(() => {
    reload().catch(() => setError("Could not load the schedule."));
  }, []);

  const toggleDay = async (d: number) => {
    setError(null);
    const next = activeDays.includes(d)
      ? activeDays.filter((x) => x !== d)
      : [...activeDays, d].sort((a, b) => a - b);
    try {
      setActiveDaysState((await setActiveDays(next)).active_days);
    } catch (err) {
      setError(errText(err));
    }
  };

  const openAdd = (prefillMinute?: number) => {
    setAdding(true);
    setChosen(null);
    setResults([]);
    setQ("");
    setAddError(null);
    setStartInput(toInput(prefillMinute ?? suggestedStart(movies)));
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
      // Chain-add: stay open, clear the search, and line the picker up with
      // the new end of the lineup so the next movie is one search away.
      const r = await reload();
      setChosen(null);
      setResults([]);
      setQ("");
      setStartInput(toInput(suggestedStart(r.movies)));
      searchRef.current?.focus();
    } catch (err) {
      setAddError(errText(err));
    }
  };

  const clearAll = async () => {
    const n = movies.length;
    if (!confirm(`Remove all ${n} movie${n === 1 ? "" : "s"} from the daily lineup?`)) return;
    setError(null);
    try {
      await clearSchedule();
      await reload();
    } catch (err) {
      setError(errText(err));
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
    <>
      <div className="card">
        <div className="eyebrow">On-Air Days <span className="muted">Days that are off show nothing — the channel goes off air</span></div>
        <div className="days">
          {WEEKDAYS.map((label, d) => (
            <button
              key={d}
              className={`day ${activeDays.includes(d) ? "on" : "off"}`}
              onClick={() => toggleDay(d)}
              title={activeDays.includes(d) ? "On air — click to turn off" : "Off air — click to turn on"}
            >
              <span className="bulb" />
              <span className="dn">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div>
        <div className="eyebrow">
          Daily Lineup <span className="muted">· {tz}</span>
          {!adding && (
            <span style={{ display: "flex", gap: 8 }}>
              {movies.length > 0 && (
                <button className="btn ghost btn-sm" onClick={clearAll}>Clear Lineup</button>
              )}
              <button className="btn btn-sm" onClick={() => openAdd()}>+ Add Movie</button>
            </span>
          )}
        </div>

        {adding && (
          <div className="card" style={{ marginBottom: 16 }}>
            <form onSubmit={runSearch} className="search-row">
              <input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the Plex library…" autoFocus />
              <button className="btn" type="submit" disabled={searching || !q.trim()}>{searching ? "…" : "Search"}</button>
              <button type="button" className="btn ghost" onClick={() => setAdding(false)}>Done</button>
            </form>

            <div style={{ display: "grid", gap: 8, margin: "14px 0" }}>
              {results.map((m) => (
                <div
                  key={m.rating_key}
                  className={`result ${chosen?.rating_key === m.rating_key ? "sel" : ""}`}
                  onClick={() => setChosen(m)}
                >
                  <span>{m.title}{m.year ? ` (${m.year})` : ""}</span>
                  <span className="muted">{m.runtime_minutes} min{m.source_available ? "" : " · file missing"}</span>
                </div>
              ))}
            </div>

            {chosen && (
              <div>
                <span className="flabel">Daily Start Time · {tz}</span>
                <input type="time" value={startInput} onChange={(e) => setStartInput(e.target.value)} style={{ maxWidth: 160 }} />
                {(() => {
                  const start = fromInput(startInput);
                  const end = start + chosen.runtime_minutes;
                  const clash = findOverlap(start, chosen.runtime_minutes, movies);
                  return (
                    <div className={clash ? "error" : "muted"} style={{ marginTop: 8, fontSize: 13 }}>
                      Ends {fmtTime(end)}{end >= 1440 ? " (next day)" : ""}
                      {clash && <> — overlaps “{clash.title}” at {fmtTime(clash.start_minute)}</>}
                    </div>
                  );
                })()}
                {!chosen.source_available && (
                  <div className="error" style={{ marginTop: 8 }}>
                    Source file not found on the mount — check the movie path mapping before scheduling this title.
                  </div>
                )}
                <div style={{ marginTop: 14 }}>
                  <button className="btn" onClick={saveAdd} disabled={!chosen.source_available}>Add “{chosen.title}”</button>
                </div>
              </div>
            )}
            {addError && <div className="error">{addError}</div>}
          </div>
        )}

        {movies.length === 0 ? (
          <div className="card empty">No movies in the daily lineup yet.</div>
        ) : (
          <div className="lineup">
            {[...movies].sort((a, b) => a.start_minute - b.start_minute).map((m, i, arr) => {
              const gap = i > 0 ? m.start_minute - endMinute(arr[i - 1]) : 0;
              return (
              <Fragment key={m.id}>
              {gap > 0 && (
                <div className="gap-row">
                  <span>{fmtDuration(gap)} off air</span>
                  <button className="chip" onClick={() => openAdd(endMinute(arr[i - 1]))}>+ Fill</button>
                </div>
              )}
              <div className="slot">
                <span className="st">{fmtTime(m.start_minute)}</span>
                <span className="thumb" style={m.poster_url ? { backgroundImage: `url(${m.poster_url})` } : undefined} />
                <span className="name">
                  {m.title}{m.year ? ` (${m.year})` : ""}
                  <span className="sub">Ends {endLabel(m)}</span>
                  {editingId === m.id && (
                    <span style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      <input type="time" value={editInput} onChange={(e) => setEditInput(e.target.value)} style={{ maxWidth: 140 }} />
                      <button className="btn btn-sm" onClick={() => saveEdit(m.id)}>Save</button>
                      <button className="btn ghost btn-sm" onClick={() => setEditingId(null)}>Cancel</button>
                    </span>
                  )}
                </span>
                <span className="act">
                  <button className="chip" onClick={() => { setEditingId(m.id); setEditInput(toInput(m.start_minute)); }}>Edit</button>
                  <button className="chip" onClick={() => remove(m.id)}>Remove</button>
                </span>
              </div>
              </Fragment>
              );
            })}
          </div>
        )}

        <div className="note">
          The lineup repeats every on-air day. Overlapping movies are rejected — a movie that starts late may run past midnight. Times are the channel's timezone ({tz}).
        </div>
      </div>
    </>
  );
}
