// Thin API client. The CSRF token returned at login is held in memory only
// (never persisted to localStorage) and sent on admin write requests.

let csrfToken: string | null = null;

export function setCsrf(token: string | null) {
  csrfToken = token;
}

async function req<T>(
  path: string,
  options: RequestInit = {},
  write = false
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (write && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const res = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// --- Types -----------------------------------------------------------------
export interface NowPlaying {
  title: string;
  year: number | null;
  poster_url: string | null;
  scheduled_start: string;
  scheduled_end: string;
  progress_seconds: number;
  runtime_seconds: number;
}

export interface UpcomingItem {
  title: string;
  year: number | null;
  poster_url: string | null;
  scheduled_start: string;
}

export interface PublicStatus {
  state: "on_air" | "off_air";
  timezone: string;
  now_playing: NowPlaying | null;
  next_up: UpcomingItem | null;
}

export interface EncodingSettings {
  maximum_resolution: "original" | "1080p" | "720p" | "480p";
  video_bitrate_kbps: number;
  audio_bitrate_kbps: number;
  encoder: string;
  encoder_preset: "fast" | "balanced" | "quality";
}

export interface ScheduledMovie {
  id: number;
  plex_rating_key: string;
  title: string;
  year: number | null;
  poster_url: string | null;
  runtime_ms: number;
  scheduled_start: string;
  scheduled_end: string;
}

export interface ScheduleDay {
  date: string;
  label: string;
  movies: ScheduledMovie[];
}

// --- Public ----------------------------------------------------------------
export const getStatus = () => req<PublicStatus>("/api/public/status");
export const getUpcoming = () => req<UpcomingItem[]>("/api/public/upcoming");

// --- Admin: auth -----------------------------------------------------------
export async function login(password: string): Promise<void> {
  const r = await req<{ ok: boolean; csrf_token: string }>(
    "/api/admin/login",
    { method: "POST", body: JSON.stringify({ password }) }
  );
  setCsrf(r.csrf_token);
}

export const logout = () =>
  req<{ ok: boolean }>("/api/admin/logout", { method: "POST" }, true);

export const whoami = async () => {
  const r = await req<{ authenticated: boolean; csrf_token: string | null }>(
    "/api/admin/whoami"
  );
  // Re-arm the in-memory CSRF token after a page reload (the session cookie
  // survives but the token held in JS memory is lost), so writes keep working.
  if (r.authenticated && r.csrf_token) setCsrf(r.csrf_token);
  return r;
};

// --- Admin: encoding -------------------------------------------------------
export const getEncoding = () => req<EncodingSettings>("/api/admin/encoding");

export const updateEncoding = (patch: Partial<EncodingSettings>) =>
  req<EncodingSettings>(
    "/api/admin/encoding",
    { method: "PATCH", body: JSON.stringify(patch) },
    true
  );

// --- Admin: schedule -------------------------------------------------------
export const getSchedule = () => req<ScheduleDay[]>("/api/admin/schedule");

export const addScheduledMovie = (plex_rating_key: string, start_local: string) =>
  req<ScheduledMovie>(
    "/api/admin/schedule",
    { method: "POST", body: JSON.stringify({ plex_rating_key, start_local }) },
    true
  );

export const updateScheduledMovie = (id: number, start_local: string) =>
  req<ScheduledMovie>(
    `/api/admin/schedule/${id}`,
    { method: "PATCH", body: JSON.stringify({ start_local }) },
    true
  );

export const deleteScheduledMovie = (id: number) =>
  req<{ ok: boolean }>(
    `/api/admin/schedule/${id}`,
    { method: "DELETE" },
    true
  );

// --- Admin: channel control & diagnostics ---------------------------------
export interface ChannelStatus {
  state: string;
  enabled: boolean;
  error: string | null;
  current_title: string | null;
  source_resolution: string | null;
  source_codec: string | null;
  output_resolution: string | null;
  video_bitrate_kbps: number | null;
  encoder: string | null;
  ffmpeg_pid: number | null;
  ffmpeg_alive: boolean;
  start_offset_seconds: number | null;
  live_offset_seconds: number | null;
  scheduled_title: string | null;
  next_title: string | null;
  next_start: string | null;
  retry_count: number;
  recent_logs: string[];
}

export interface Diagnostics {
  plex_reachable: boolean;
  database_reachable: boolean;
  movie_mount_readable: boolean;
  stream_dir_writable: boolean;
  ffmpeg_installed: boolean;
  ffprobe_installed: boolean;
  nvenc_listed: boolean;
  nvenc_available: boolean;
  nvenc_detail: string;
  ffmpeg_process_alive: boolean;
}

export const getChannelStatus = () =>
  req<ChannelStatus>("/api/admin/channel/status");

export const startChannel = () =>
  req<ChannelStatus>("/api/admin/channel/start", { method: "POST" }, true);

export const stopChannel = () =>
  req<ChannelStatus>("/api/admin/channel/stop", { method: "POST" }, true);

export const getDiagnostics = () => req<Diagnostics>("/api/admin/diagnostics");
