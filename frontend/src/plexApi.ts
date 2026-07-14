// Plex admin API calls. Separate module to keep the surface tidy. All requests
// are authenticated by the admin session cookie; responses never contain the
// Plex token or raw filesystem paths (the backend strips them).
import { ApiError } from "./api";

export interface PlexStatus {
  configured: boolean;
  reachable: boolean;
  library_found: boolean;
  library_name: string;
}

export interface PlexMovie {
  rating_key: string;
  title: string;
  year: number | null;
  summary: string;
  poster_url: string | null;
  runtime_ms: number;
  runtime_minutes: number;
  source_resolution: string | null;
  video_codec: string | null;
  audio_codec: string | null;
  container: string | null;
  source_available: boolean;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const getPlexStatus = () => get<PlexStatus>("/api/admin/plex/status");

export const searchPlex = (q: string) =>
  get<PlexMovie[]>(`/api/admin/plex/search?q=${encodeURIComponent(q)}`);
