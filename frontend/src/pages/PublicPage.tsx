import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { getStatus, getUpcoming, PublicStatus, UpcomingItem } from "../api";

const STREAM_URL = "/stream/channel.m3u8";

function fmtTime(iso: string, tz: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
      timeZone: tz,
    });
  } catch {
    return new Date(iso).toLocaleTimeString();
  }
}

function fmtDayTime(iso: string, tz: string): string {
  try {
    return new Date(iso).toLocaleString([], {
      weekday: "long",
      hour: "numeric",
      minute: "2-digit",
      timeZone: tz,
    });
  } catch {
    return new Date(iso).toLocaleString();
  }
}

// Live TV player: attach HLS, disable seeking, keep near the live edge.
function LivePlayer() {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let hls: Hls | null = null;

    if (Hls.isSupported()) {
      // Keep the client's memory footprint small: by default hls.js retains an
      // unbounded back-buffer (it grew to minutes, ~150 MB, before the browser
      // evicted). Cap the buffer tightly for a live channel that only needs to
      // stay near the live edge.
      hls = new Hls({
        liveSyncDurationCount: 3,
        enableWorker: true,
        backBufferLength: 15, // seconds kept behind the playhead (rewind window)
        maxBufferLength: 15, // target seconds buffered ahead
        maxBufferSize: 20 * 1000 * 1000, // hard cap ~20 MB regardless of bitrate
      });
      hls.loadSource(STREAM_URL);
      hls.attachMedia(video);
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      // Safari / iOS native HLS.
      video.src = STREAM_URL;
    }

    // Prevent seeking: snap back to the live edge on any seek attempt.
    const preventSeek = () => {
      if (video.seekable.length > 0) {
        const liveEdge = video.seekable.end(video.seekable.length - 1);
        if (Math.abs(video.currentTime - liveEdge) > 2) {
          video.currentTime = liveEdge;
        }
      }
    };
    video.addEventListener("seeking", preventSeek);

    return () => {
      video.removeEventListener("seeking", preventSeek);
      if (hls) hls.destroy();
    };
  }, []);

  return (
    <div className="player">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        controls
        controlsList="nodownload noplaybackrate"
        disablePictureInPicture={false}
      />
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
        if (s.state === "on_air") {
          const u = await getUpcoming();
          if (alive) setUpcoming(u);
        } else {
          setUpcoming([]);
        }
      } catch {
        /* transient; retried on next tick */
      }
    };
    load();
    const id = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const tz = status?.timezone ?? "UTC";

  if (!status) {
    return (
      <div className="container">
        <div className="brand">Movie Channel</div>
        <div className="offair">
          <h1>Loading…</h1>
        </div>
      </div>
    );
  }

  if (status.state === "off_air") {
    const next = status.next_up;
    return (
      <div className="container">
        <div className="brand">Movie Channel</div>
        <div className="offair">
          <h1>OFF AIR</h1>
          {next ? (
            <p className="now-meta">
              Next movie: <strong>{next.title}</strong>
              <br />
              Starts {fmtDayTime(next.scheduled_start, tz)}
            </p>
          ) : (
            <p className="now-meta">No movies scheduled.</p>
          )}
        </div>
      </div>
    );
  }

  const np = status.now_playing!;
  const pct = np.runtime_seconds
    ? Math.min(100, (np.progress_seconds / np.runtime_seconds) * 100)
    : 0;

  return (
    <div className="container">
      <div className="topbar">
        <div className="brand">Movie Channel</div>
        <span className="status-pill on">
          <span className="dot" /> Now Playing
        </span>
      </div>

      <div className="grid">
        <div>
          {np.poster_url ? (
            <img className="poster" src={np.poster_url} alt={np.title} />
          ) : (
            <div className="poster" />
          )}
        </div>
        <div>
          <div className="now-title">{np.title}</div>
          <div className="now-meta">
            {np.year ? `${np.year} · ` : ""}
            {fmtTime(np.scheduled_start, tz)} – {fmtTime(np.scheduled_end, tz)}
          </div>
          <div className="progress">
            <span style={{ width: `${pct}%` }} />
          </div>
          <LivePlayer />
        </div>
      </div>

      <div className="section-label">Up Next</div>
      <div className="panel">
        {upcoming.length === 0 && (
          <div className="empty">Nothing else scheduled.</div>
        )}
        {upcoming.map((u, i) => (
          <div className="up-next-row" key={i}>
            <span>
              {u.title}
              {u.year ? ` (${u.year})` : ""}
            </span>
            <span className="now-meta">{fmtTime(u.scheduled_start, tz)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
