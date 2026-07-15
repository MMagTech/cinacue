import { useEffect, useRef, useState, useCallback } from "react";
import Hls from "hls.js";
import { getStatus, getUpcoming, PublicStatus, UpcomingItem } from "../api";

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
  const hideTimer = useRef<number | undefined>(undefined);
  const [chrome, setChrome] = useState(true);
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let hls: Hls | null = null;
    if (Hls.isSupported()) {
      hls = new Hls({
        liveSyncDurationCount: 3,
        enableWorker: true,
        backBufferLength: 15,
        maxBufferLength: 15,
        maxBufferSize: 20 * 1000 * 1000,
      });
      hls.loadSource(STREAM_URL);
      hls.attachMedia(video);
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = STREAM_URL;
    }
    const preventSeek = () => {
      if (video.seekable.length > 0) {
        const edge = video.seekable.end(video.seekable.length - 1);
        if (Math.abs(video.currentTime - edge) > 2) video.currentTime = edge;
      }
    };
    video.addEventListener("seeking", preventSeek);
    return () => {
      video.removeEventListener("seeking", preventSeek);
      if (hls) hls.destroy();
    };
  }, []);

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
      <div className={`player-overlay${chrome ? "" : " hidden"}`}>
        <div className="progress" style={{ marginBottom: 12 }}>
          <button className="chip" onClick={toggleMute} title={muted ? "Unmute" : "Mute"}>
            {muted ? "🔇" : "🔊"}
          </button>
          <span className="time">{fmtDur(progressSeconds)}</span>
          <div className="bar"><i style={{ width: `${pct}%` }} /></div>
          <span className="time">{fmtDur(runtimeSeconds)}</span>
          <button className="chip" onClick={fullscreen} title="Fullscreen">⛶</button>
        </div>
      </div>
    </div>
  );
}

export default function PublicPage() {
  const [status, setStatus] = useState<PublicStatus | null>(null);
  const [upcoming, setUpcoming] = useState<UpcomingItem[]>([]);

  useEffect(() => {
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
  }, []);

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
