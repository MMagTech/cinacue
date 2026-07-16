import { useEffect, useRef, useState, useCallback } from "react";
import Hls from "hls.js";
import {
  getStatus,
  getUpcoming,
  getAccessState,
  submitAccessCode,
  PublicStatus,
  UpcomingItem,
  ApiError,
} from "../api";

const STREAM_URL = "/stream/channel.m3u8";

function fmtDur(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(h > 0 ? 2 : 1, "0");
  return h > 0
    ? `${h}:${mm}:${String(sec).padStart(2, "0")}`
    : `${mm}:${String(sec).padStart(2, "0")}`;
}

function fmtOfDay(iso: string, tz: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: tz });
  } catch {
    return new Date(iso).toLocaleTimeString();
  }
}

function countdown(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "starting now";
  const min = Math.round(diff / 60000);
  if (min < 60) return `in ${min} min`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `in ${hr} hr`;
  return `in ${Math.round(hr / 24)} days`;
}

function TopBar({ live, tz }: { live: boolean; tz: string }) {
  const [now, setNow] = useState("");
  useEffect(() => {
    const tick = () =>
      setNow(new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: tz }));
    tick();
    const id = setInterval(tick, 20000);
    return () => clearInterval(id);
  }, [tz]);
  return (
    <div className="v-top">
      <span className="wordmark">CINA<b>CUE</b></span>
      {live ? (
        <span className="onair"><span className="live" /> On Air</span>
      ) : (
        <span className="offair-badge"><span className="dot" /> Off Air</span>
      )}
      <span className="clock">{now}</span>
    </div>
  );
}

function Player({ progressSeconds, runtimeSeconds }: { progressSeconds: number; runtimeSeconds: number }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const hideTimer = useRef<number | undefined>(undefined);
  // Captions are rendered by us (not the browser) so size/position are fully
  // controllable and consistent across browsers — Firefox in particular gives
  // almost no control over native ::cue styling. cuesRef holds the parsed cues;
  // a rAF loop picks the active one against the video clock. subsOnRef mirrors
  // subsOn so that loop always sees the latest toggle state.
  const cuesRef = useRef<{ start: number; end: number; text: string }[]>([]);
  const subsOnRef = useRef(false);
  const [chrome, setChrome] = useState(true);
  const [muted, setMuted] = useState(true);
  const [subsAvailable, setSubsAvailable] = useState(false);
  const [cueText, setCueText] = useState("");
  const [subsOn, setSubsOn] = useState(() => {
    try {
      return localStorage.getItem("cc_subs") === "1";
    } catch {
      return false;
    }
  });
  subsOnRef.current = subsOn;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let destroyed = false;
    let reloadTimer: number | undefined;
    // Movie transitions wipe and regenerate the playlist, and captions coming
    // and going switch it between a plain media playlist and a master playlist.
    // Native recovery handles the routine gaps; a full re-parse of the source
    // is the fallback that re-detects the structure. This counter decides when
    // to escalate, and is cleared once playback is healthy again.
    let fatalCount = 0;

    const teardown = () => {
      const hls = hlsRef.current;
      if (hls) {
        hls.destroy();
        hlsRef.current = null;
      }
      cuesRef.current = [];
      setCueText("");
    };

    const init = () => {
      if (destroyed) return;
      cuesRef.current = [];
      if (Hls.isSupported()) {
        const hls = new Hls({
          liveSyncDurationCount: 3,
          enableWorker: true,
          backBufferLength: 15,
          maxBufferLength: 15,
          maxBufferSize: 20 * 1000 * 1000,
          renderTextTracksNatively: false,
        });
        hlsRef.current = hls;
        hls.loadSource(STREAM_URL);
        hls.attachMedia(video);
        hls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, () => {
          setSubsAvailable((hlsRef.current?.subtitleTracks?.length ?? 0) > 0);
        });
        hls.on(Hls.Events.CUES_PARSED, (_e, data) => {
          if (data.type !== "subtitles") return;
          const store = cuesRef.current;
          for (const c of data.cues as VTTCue[]) {
            store.push({ start: c.startTime, end: c.endTime, text: c.text });
          }
          // Bound memory on the long-running live stream.
          if (store.length > 400) store.splice(0, store.length - 400);
        });
        hls.on(Hls.Events.FRAG_BUFFERED, () => {
          fatalCount = 0;
        });
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (!data.fatal) return;
          fatalCount += 1;
          if (fatalCount <= 2 && data.type === Hls.ErrorTypes.NETWORK_ERROR) {
            hlsRef.current?.startLoad();
            return;
          }
          if (fatalCount <= 2 && data.type === Hls.ErrorTypes.MEDIA_ERROR) {
            hlsRef.current?.recoverMediaError();
            return;
          }
          // Persistent failure or a media/master structure change: re-parse
          // the source from scratch after a short beat.
          teardown();
          setSubsAvailable(false);
          reloadTimer = window.setTimeout(init, 1200);
        });
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        // Safari plays the master (and its subtitle rendition) natively.
        video.src = STREAM_URL;
        video.addEventListener("loadedmetadata", () => {
          setSubsAvailable(video.textTracks.length > 0);
        });
      }
    };

    init();

    // Draw the active caption ourselves. Runs off the video clock so it always
    // matches whatever frame is on screen; only re-renders when the line changes.
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const v = videoRef.current;
      if (!v || !subsOnRef.current) {
        setCueText((prev) => (prev === "" ? prev : ""));
        return;
      }
      const t = v.currentTime;
      let text = "";
      for (const c of cuesRef.current) {
        if (t >= c.start && t < c.end) {
          text = c.text;
          break;
        }
      }
      setCueText((prev) => (prev === text ? prev : text));
    };
    raf = requestAnimationFrame(draw);

    const preventSeek = () => {
      if (video.seekable.length > 0) {
        const edge = video.seekable.end(video.seekable.length - 1);
        if (Math.abs(video.currentTime - edge) > 2) video.currentTime = edge;
      }
    };
    video.addEventListener("seeking", preventSeek);
    return () => {
      destroyed = true;
      window.clearTimeout(reloadTimer);
      cancelAnimationFrame(raf);
      video.removeEventListener("seeking", preventSeek);
      teardown();
    };
  }, []);

  // Apply the caption preference whenever it changes, or when a new stream
  // reports whether captions are available. Default off so they never surprise.
  useEffect(() => {
    try {
      localStorage.setItem("cc_subs", subsOn ? "1" : "0");
    } catch {
      /* private mode */
    }
    const hls = hlsRef.current;
    const video = videoRef.current;
    if (hls) {
      const on = subsOn && (hls.subtitleTracks?.length ?? 0) > 0;
      // Selecting the track drives cue parsing (CUES_PARSED); -1 stops it.
      hls.subtitleTrack = on ? 0 : -1;
      if (!on) {
        cuesRef.current = [];
        setCueText("");
      }
    } else if (video) {
      // Safari native path: toggle the browser-rendered track.
      for (let i = 0; i < video.textTracks.length; i++) {
        video.textTracks[i].mode = subsOn ? "showing" : "hidden";
      }
    }
  }, [subsOn, subsAvailable]);

  // Auto-hide the overlay after inactivity; reveal on pointer/touch.
  const wake = useCallback(() => {
    setChrome(true);
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => setChrome(false), 3000);
  }, []);
  useEffect(() => {
    wake();
    return () => window.clearTimeout(hideTimer.current);
  }, [wake]);

  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  };
  const toggleSubs = () => setSubsOn((v) => !v);
  const fullscreen = () => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else el.requestFullscreen?.().catch(() => {});
  };

  const pct = runtimeSeconds ? Math.min(100, (progressSeconds / runtimeSeconds) * 100) : 0;

  return (
    <div
      className="player"
      ref={wrapRef}
      onMouseMove={wake}
      onTouchStart={wake}
      onClick={wake}
    >
      <video ref={videoRef} autoPlay playsInline muted={muted} />
      {subsOn && cueText && (
        <div className={`cc-box${chrome ? " up" : ""}`}>{cueText}</div>
      )}
      {muted && (
        <button className="sound-hint" onClick={toggleMute} aria-label="Turn on sound">
          <span aria-hidden="true">🔊</span> Tap For Sound
        </button>
      )}
      <div className={`player-overlay${chrome ? "" : " hidden"}`}>
        <div className="progress" style={{ marginBottom: 12 }}>
          <button className="chip" onClick={toggleMute} aria-label={muted ? "Unmute" : "Mute"} title={muted ? "Unmute" : "Mute"}>
            <span aria-hidden="true">{muted ? "🔇" : "🔊"}</span>
          </button>
          {subsAvailable && (
            <button
              className={`chip cc${subsOn ? " on" : ""}`}
              onClick={toggleSubs}
              aria-label={subsOn ? "Turn Off Subtitles" : "Turn On Subtitles"}
              aria-pressed={subsOn}
              title={subsOn ? "Subtitles On" : "Subtitles Off"}
            >
              <span aria-hidden="true">CC</span>
            </button>
          )}
          <span className="time">{fmtDur(progressSeconds)}</span>
          <div className="bar"><i style={{ width: `${pct}%` }} /></div>
          <span className="time">{fmtDur(runtimeSeconds)}</span>
          <button className="chip" onClick={fullscreen} aria-label="Toggle fullscreen" title="Fullscreen">
            <span aria-hidden="true">⛶</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function AccessGate({ onGranted }: { onGranted: () => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await submitAccessCode(code);
      onGranted();
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts — try again in a little while.");
      } else {
        setError("Incorrect access code.");
      }
      setBusy(false);
    }
  };

  return (
    <div className="viewer">
      <div className="v-top"><span className="wordmark">CINA<b>CUE</b></span></div>
      <div className="login-wrap">
        <form className="card login-card" onSubmit={submit}>
          <div className="wordmark" style={{ marginBottom: 4 }}>CINA<b>CUE</b></div>
          <div className="muted" style={{ fontSize: 13, marginBottom: 20 }}>Enter The Access Code To Watch</div>
          <span className="flabel">Access Code</span>
          <input type="password" value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
          {error && <div className="error">{error}</div>}
          <div style={{ marginTop: 18 }}>
            <button className="btn" type="submit" disabled={busy || !code}>{busy ? "Checking…" : "Watch"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function PublicPage() {
  const [status, setStatus] = useState<PublicStatus | null>(null);
  const [upcoming, setUpcoming] = useState<UpcomingItem[]>([]);
  // null = checking; true = may watch; false = needs the shared code
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    getAccessState()
      .then((a) => setAllowed(!a.required || a.granted))
      .catch(() => setAllowed(true)); // if the check fails, don't hard-block
  }, []);

  useEffect(() => {
    if (!allowed) return;
    let alive = true;
    const load = async () => {
      try {
        const s = await getStatus();
        if (!alive) return;
        setStatus(s);
        const u = await getUpcoming();
        if (alive) setUpcoming(u);
      } catch {
        /* transient */
      }
    };
    load();
    const id = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [allowed]);

  if (allowed === null) {
    return (
      <div className="viewer">
        <div className="v-top"><span className="wordmark">CINA<b>CUE</b></span></div>
      </div>
    );
  }
  if (!allowed) {
    return <AccessGate onGranted={() => setAllowed(true)} />;
  }

  const tz = status?.timezone ?? "UTC";
  const onAir = status?.state === "on_air";
  const np = status?.now_playing ?? null;

  const rail = (
    <div className="rail-wrap">
      <div className="rail-head">
        <span className="lab">{onAir ? "Up Next" : "Later Today"}</span>
        <span className="rule" />
      </div>
      {upcoming.length === 0 ? (
        <div className="rail-empty">Nothing else scheduled.</div>
      ) : (
        <div className="rail">
          {upcoming.map((u, i) => (
            <div className="up" key={i}>
              <div
                className="th"
                style={u.poster_url ? { backgroundImage: `url(${u.poster_url})` } : undefined}
              />
              <p className="t">{u.title}</p>
              <span className="s">{fmtOfDay(u.scheduled_start, tz)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="viewer">
      <TopBar live={onAir} tz={tz} />
      <div className="stage">
        {onAir && np ? (
          <>
            <Player progressSeconds={np.progress_seconds} runtimeSeconds={np.runtime_seconds} />
            <div className="rail-wrap" style={{ paddingTop: 18 }}>
              <div className="np-current" style={{ marginBottom: 4 }}>
                <span className="np-k">Now Playing</span>
              </div>
              <h1 className="np-title" style={{ fontSize: 24, marginBottom: 4 }}>
                {np.title}
                {np.year ? <span>&nbsp;({np.year})</span> : null}
              </h1>
              <p className="np-tags">
                {fmtOfDay(np.scheduled_start, tz)} – {fmtOfDay(np.scheduled_end, tz)}
              </p>
            </div>
          </>
        ) : (
          <div className="player standby">
            <div className="still" />
            <div className="standby-center">
              {status?.next_up ? (
                <>
                  <h1>Nothing On Right Now</h1>
                  <p className="line">Up Next — <b>{status.next_up.title}</b></p>
                  <p className="count">
                    {fmtOfDay(status.next_up.scheduled_start, tz)} · {countdown(status.next_up.scheduled_start)}
                  </p>
                </>
              ) : (
                <>
                  <h1>Off Air</h1>
                  <p className="line">No Programming Scheduled</p>
                </>
              )}
            </div>
          </div>
        )}
        {rail}
      </div>
    </div>
  );
}
