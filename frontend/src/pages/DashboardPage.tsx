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
  return `${h > 0 ? h + "h " : ""}${m}m ${s}s`;
}

const stateColor: Record<string, string> = {
  streaming: "var(--ok)",
  starting: "var(--accent)",
  stopping: "var(--accent)",
  error: "var(--danger)",
  offline: "var(--muted)",
};

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
      <span className="now-meta">{label}</span>
      <span>{value ?? "—"}</span>
    </div>
  );
}

function Check({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return (
    <div className="up-next-row">
      <span>{label}</span>
      <span style={{ color: ok ? "var(--ok)" : "var(--danger)" }}>
        {ok ? "OK" : "FAIL"}
        {detail ? ` · ${detail}` : ""}
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
      setError("Action failed. Check your session and try again.");
    } finally {
      setBusy(false);
    }
  };

  const runDiag = async () => {
    setDiagBusy(true);
    try {
      setDiag(await getDiagnostics());
    } catch {
      setError("Diagnostics failed.");
    } finally {
      setDiagBusy(false);
    }
  };

  if (!st) {
    return <div className="panel">Loading…</div>;
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <div className="topbar" style={{ marginBottom: 4 }}>
          <span className="status-pill" style={{ color: stateColor[st.state] }}>
            <span className="dot" /> {st.state.toUpperCase()}
            {st.enabled ? "" : " (channel off)"}
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" onClick={() => toggle(true)} disabled={busy || st.enabled}>
              Start
            </button>
            <button
              className="btn secondary"
              onClick={() => toggle(false)}
              disabled={busy || !st.enabled}
            >
              Stop
            </button>
          </div>
        </div>
        {st.error && <div className="error">{st.error}</div>}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="panel">
        <Row label="Current movie" value={st.current_title ?? st.scheduled_title} />
        <Row label="Live position" value={fmtOffset(st.live_offset_seconds)} />
        <Row label="Started at offset" value={fmtOffset(st.start_offset_seconds)} />
        <Row
          label="Source"
          value={
            st.source_resolution
              ? `${st.source_resolution}${st.source_codec ? " " + st.source_codec : ""}`
              : "—"
          }
        />
        <Row label="Actual output" value={st.output_resolution} />
        <Row
          label="Video bitrate"
          value={st.video_bitrate_kbps ? `${st.video_bitrate_kbps} kbps` : "—"}
        />
        <Row label="Encoder" value={st.encoder} />
        <Row
          label="FFmpeg"
          value={
            st.ffmpeg_alive ? `running (pid ${st.ffmpeg_pid})` : "not running"
          }
        />
        <Row label="Retries" value={st.retry_count} />
        <Row label="Up next" value={st.next_title} />
      </div>

      <div className="panel">
        <div className="topbar" style={{ marginBottom: 8 }}>
          <strong>Diagnostics</strong>
          <button className="btn secondary" onClick={runDiag} disabled={diagBusy}>
            {diagBusy ? "Checking…" : "Run checks"}
          </button>
        </div>
        {diag ? (
          <div>
            <Check ok={diag.database_reachable} label="Database reachable" />
            <Check ok={diag.plex_reachable} label="Plex reachable" />
            <Check ok={diag.movie_mount_readable} label="Movie mount readable" />
            <Check ok={diag.stream_dir_writable} label="Stream dir writable" />
            <Check ok={diag.ffmpeg_installed} label="FFmpeg installed" />
            <Check ok={diag.ffprobe_installed} label="FFprobe installed" />
            <Check ok={diag.nvenc_listed} label="h264_nvenc listed" />
            <Check
              ok={diag.nvenc_available}
              label="NVENC hardware encode"
              detail={diag.nvenc_detail}
            />
            <Check ok={diag.ffmpeg_process_alive} label="FFmpeg process alive" />
          </div>
        ) : (
          <div className="empty">Run checks to verify Plex, the mount, FFmpeg, and NVENC.</div>
        )}
      </div>

      <div className="panel">
        <strong>Recent FFmpeg log</strong>
        <pre
          style={{
            marginTop: 8,
            maxHeight: 220,
            overflow: "auto",
            fontSize: 12,
            color: "var(--muted)",
            whiteSpace: "pre-wrap",
          }}
        >
          {st.recent_logs.length ? st.recent_logs.join("\n") : "No output yet."}
        </pre>
      </div>
    </div>
  );
}
