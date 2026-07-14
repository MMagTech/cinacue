import { useEffect, useState } from "react";
import { getEncoding, updateEncoding, EncodingSettings } from "../api";

const RES: EncodingSettings["maximum_resolution"][] = [
  "original",
  "1080p",
  "720p",
  "480p",
];
const AUDIO = [128, 160, 192, 256];
const PRESETS: EncodingSettings["encoder_preset"][] = [
  "fast",
  "balanced",
  "quality",
];

export default function EncodingPage() {
  const [cfg, setCfg] = useState<EncodingSettings | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getEncoding()
      .then(setCfg)
      .catch(() => setError("Could not load encoding settings."));
  }, []);

  if (!cfg) {
    return <div className="panel">Loading…</div>;
  }

  const patch = (p: Partial<EncodingSettings>) => {
    setCfg({ ...cfg, ...p });
    setSaved(false);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await updateEncoding({
        maximum_resolution: cfg.maximum_resolution,
        video_bitrate_kbps: cfg.video_bitrate_kbps,
        audio_bitrate_kbps: cfg.audio_bitrate_kbps,
        encoder_preset: cfg.encoder_preset,
      });
      setCfg(updated);
      setSaved(true);
    } catch {
      setError("Could not save. Check your session and try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <label>Maximum resolution</label>
      <div className="pill-row">
        {RES.map((r) => (
          <button
            key={r}
            className={`choice ${cfg.maximum_resolution === r ? "active" : ""}`}
            onClick={() => patch({ maximum_resolution: r })}
          >
            {r === "original" ? "Original" : r}
          </button>
        ))}
      </div>

      <label>Video bitrate (kbps)</label>
      <input
        type="number"
        min={500}
        max={100000}
        step={500}
        value={cfg.video_bitrate_kbps}
        onChange={(e) =>
          patch({ video_bitrate_kbps: Number(e.target.value) })
        }
      />

      <label>Audio bitrate (kbps)</label>
      <div className="pill-row">
        {AUDIO.map((a) => (
          <button
            key={a}
            className={`choice ${cfg.audio_bitrate_kbps === a ? "active" : ""}`}
            onClick={() => patch({ audio_bitrate_kbps: a })}
          >
            {a}
          </button>
        ))}
      </div>

      <label>Encoder preset</label>
      <div className="pill-row">
        {PRESETS.map((p) => (
          <button
            key={p}
            className={`choice ${cfg.encoder_preset === p ? "active" : ""}`}
            onClick={() => patch({ encoder_preset: p })}
          >
            {p[0].toUpperCase() + p.slice(1)}
          </button>
        ))}
      </div>

      <label>Encoder</label>
      <input value={cfg.encoder} disabled />

      <div style={{ marginTop: 20, display: "flex", gap: 12, alignItems: "center" }}>
        <button className="btn" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        {saved && <span style={{ color: "var(--ok)" }}>Saved</span>}
      </div>

      {error && <div className="error">{error}</div>}

      <div className="note">
        The selected resolution is a <strong>maximum</strong>. Lower-resolution
        sources will remain at their original resolution — the channel never
        upscales, crops, or stretches. Upscaling is always disabled.
      </div>
    </div>
  );
}
