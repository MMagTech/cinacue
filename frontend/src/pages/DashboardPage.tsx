import { useEffect, useState } from "react";
import {
  getChannelStatus,
  startChannel,
  stopChannel,
  getDiagnostics,
  ChannelStatus,
  Diagnostics,
  ApiError,
} from "../api";

function fmtOffset(sec: number | null): string {
  if (sec == null) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const mm = String(m).padStart(h > 0 ? 2 : 1, "0");
  return h > 0 ? `${h}:${mm}:${String(s).padStart(2, "0")}` : `${mm}:${String(s).padStart(2, "0")}`;
}

function fmtUptime(sec: number | null): string {
  if (sec == null) return "—";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function Tile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="tile">
      <div className="l">{label}</div>
      <div className="v">{value ?? "—"}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  );
}

function Check({ ok, name, detail }: { ok: boolean; name: string; detail?: string }) {
  return (
    <div className="row">
      <span className="name">
        {name}
        {detail ? <small>{detail}</small> : null}
      </span>
      <span className={`res ${ok ? "ok" : "bad"}`}>
        {ok ? <span className="tick" /> : <span className="cross">✕</span>}
        {ok ? "OK" : "Failed"}
      </span>
    </div>
  );
}

export default function DashboardPage() {
  const [st, setSt] = useState<ChannelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);

  const load = async () => {
    try {
      setSt(await getChannelStatus());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      setError("Could not load channel status.");
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  const toggle = async (start: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setSt(start ? await startChannel() : await stopChannel());
    } catch {
      setError("That didn't go through — reload the page and sign in again.");
    } finally {
      setBusy(false);
    }
  };

  const runDiag = async () => {
    setDiagBusy(true);
    try {
      setDiag(await getDiagnostics());
    } catch {
      setError("System checks failed to run.");
    } finally {
      setDiagBusy(false);
    }
  };

  if (!st) return <div className="panel">Loading…</div>;

  const streaming = st.state === "streaming" && st.enabled;
  const gpuVal = st.gpu_encode_percent != null ? `${st.gpu_encode_percent}%` : "—";

  return (
    <>
      <div className="dash-status">
        {streaming ? (
          <span className="live-pill"><span className="live" /> Streaming</span>
        ) : (
          <span className="off-pill">
            <span className="dot" /> {st.enabled ? st.state : "Channel Off"}
          </span>
        )}
        <span className="up">Up {fmtUptime(st.uptime_seconds)} · {st.retry_count} Retries</span>
        <span className="spacer" />
        <button className="btn" onClick={() => toggle(true)} disabled={busy || st.enabled}>Start</button>
        <button className="btn stop" onClick={() => toggle(false)} disabled={busy || !st.enabled}>Stop</button>
      </div>

      {(st.error || error) && <div className="error">{st.error || error}</div>}

      <div className="tiles">
        <Tile label="Now Playing" value={st.current_title ?? st.scheduled_title ?? "—"} />
        <Tile label="Live Position" value={fmtOffset(st.live_offset_seconds)} />
        <Tile
          label="Output"
          value={st.output_resolution ?? "—"}
          sub={st.encoder ? `${st.encoder}${st.video_bitrate_kbps ? " · " + st.video_bitrate_kbps + " kbps" : ""}` : undefined}
        />
        <Tile label="GPU Encode" value={gpuVal} sub={st.gpu_name ?? "GPU"} />
        <Tile
          label="Source"
          value={st.source_resolution ?? "—"}
          sub={st.source_codec ?? undefined}
        />
        <Tile
          label="FFmpeg"
          value={<><span className={st.ffmpeg_alive ? "ok-dot" : "dead-dot"} />{st.ffmpeg_alive ? `pid ${st.ffmpeg_pid}` : "Stopped"}</>}
          sub={`${st.retry_count} Restarts`}
        />
        <Tile label="Retries" value={st.retry_count} />
        <Tile label="Up Next" value={st.next_title ?? "—"} />
      </div>

      <div className="dash-cols">
        <div>
          <div className="panel-head">
            <h3>System Checks</h3>
            <button className="chip" onClick={runDiag} disabled={diagBusy}>
              {diagBusy ? "Checking…" : "Run Checks"}
            </button>
          </div>
          {diag ? (
            <div className="diag">
              <Check ok={diag.plex_reachable} name="Plex Server" />
              <Check ok={diag.database_reachable} name="Database" />
              <Check ok={diag.movie_mount_readable} name="Movie Mount" />
              <Check ok={diag.stream_dir_writable} name="Stream Buffer" detail="RAM · /stream" />
              <Check ok={diag.ffmpeg_installed && diag.ffprobe_installed} name="FFmpeg / FFprobe" />
              <Check ok={diag.nvenc_available} name="NVENC" detail={diag.nvenc_detail} />
            </div>
          ) : (
            <div className="panel empty">Run checks to verify Plex, the mount, FFmpeg, and NVENC.</div>
          )}
        </div>
        <div>
          <div className="panel-head"><h3>Recent Activity</h3></div>
          <div className="logs">
            {st.recent_logs.length ? st.recent_logs.map((l, i) => <div key={i}>{l}</div>) : <div>No output yet.</div>}
          </div>
        </div>
      </div>
    </>
  );
}
