import { useEffect, useState } from "react";
import { getEncoding, updateEncoding, EncodingSettings } from "../api";

const RES: EncodingSettings["maximum_resolution"][] = ["original", "1080p", "720p", "480p"];
const AUDIO = [128, 160, 192, 256];
const PRESETS: EncodingSettings["encoder_preset"][] = ["fast", "balanced", "quality"];
const PRESET_NVENC: Record<string, string> = { fast: "p2", balanced: "p4", quality: "p6" };

function cap(s: string) {
  return s[0].toUpperCase() + s.slice(1);
}

export default function EncodingPage() {
  const [cfg, setCfg] = useState<EncodingSettings | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getEncoding().then(setCfg).catch(() => setError("Could not load encoding settings."));
  }, []);

  if (!cfg) return <div className="panel">Loading…</div>;

  const patch = (p: Partial<EncodingSettings>) => {
    setCfg({ ...cfg, ...p });
    setSaved(false);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      setCfg(
        await updateEncoding({
          maximum_resolution: cfg.maximum_resolution,
          video_bitrate_kbps: cfg.video_bitrate_kbps,
          audio_bitrate_kbps: cfg.audio_bitrate_kbps,
          encoder_preset: cfg.encoder_preset,
        })
      );
      setSaved(true);
    } catch {
      setError("Couldn't save — reload the page and sign in again.");
    } finally {
      setBusy(false);
    }
  };

  const mbps = (cfg.video_bitrate_kbps / 1000).toFixed(1);
  const rewindMin = Math.max(1, Math.round(20000 / cfg.video_bitrate_kbps));
  const outRes = cfg.maximum_resolution === "original" ? "Source" : cfg.maximum_resolution;

  return (
    <div className="enc-grid">
      <div className="card">
        <div className="field">
          <span className="flabel">Maximum Resolution</span>
          <div className="seg">
            {RES.map((r) => (
              <button
                key={r}
                className={cfg.maximum_resolution === r ? "on" : ""}
                onClick={() => patch({ maximum_resolution: r })}
              >
                {r === "original" ? "Original" : r}
              </button>
            ))}
          </div>
          <p className="fhelp">A ceiling, not a target — lower-res films stay original. <b>Never upscaled, cropped, or stretched.</b></p>
        </div>

        <div className="field">
          <span className="flabel">Video Bitrate</span>
          <div className="slider-row">
            <input
              type="range"
              min={1000}
              max={16000}
              step={250}
              value={cfg.video_bitrate_kbps}
              onChange={(e) => patch({ video_bitrate_kbps: Number(e.target.value) })}
            />
            <span className="slider-val">{cfg.video_bitrate_kbps} kbps</span>
          </div>
          <p className="fhelp">≈ <b>{mbps} Mbps per viewer</b> — higher bitrate means fewer concurrent remote viewers per uplink.</p>
        </div>

        <div className="field">
          <span className="flabel">Audio Bitrate <span className="muted">· kbps</span></span>
          <div className="seg">
            {AUDIO.map((a) => (
              <button key={a} className={cfg.audio_bitrate_kbps === a ? "on" : ""} onClick={() => patch({ audio_bitrate_kbps: a })}>
                {a}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <span className="flabel">Encoder Preset</span>
          <div className="seg">
            {PRESETS.map((p) => (
              <button key={p} className={cfg.encoder_preset === p ? "on" : ""} onClick={() => patch({ encoder_preset: p })}>
                {cap(p)}
              </button>
            ))}
          </div>
          <p className="fhelp">Balanced maps to NVENC <b>{PRESET_NVENC[cfg.encoder_preset]}</b> — the quality/throughput trade-off.</p>
        </div>

        <div className="field">
          <span className="flabel">Encoder</span>
          <div className="locked">{cfg.encoder}<span className="verified">GPU</span></div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <button className="btn" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save Changes"}</button>
          <span className="muted" style={{ fontSize: 12.5 }}>
            {saved ? "Saved — applies to the next movie." : "Applies to the next movie, never mid-stream."}
          </span>
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      <div className="card preview-card">
        <h3>Output Preview</h3>
        <div className="flow">
          <div className="box"><div className="bl">Source</div><div className="bv">Plex File</div></div>
          <span className="arrow">→</span>
          <div className="box"><div className="bl">Broadcast</div><div className="bv">{outRes} H.264</div></div>
        </div>
        <div className="pv-row"><span className="k">Video</span><span className="v">{outRes} · {mbps} Mbps</span></div>
        <div className="pv-row"><span className="k">Audio</span><span className="v">AAC {cfg.audio_bitrate_kbps}k · stereo</span></div>
        <div className="pv-row"><span className="k">Encoder</span><span className="v">{cfg.encoder} · {PRESET_NVENC[cfg.encoder_preset]}</span></div>
        <div className="pv-row"><span className="k">Rewind Buffer</span><span className="v">~{rewindMin} min</span></div>
      </div>
    </div>
  );
}
