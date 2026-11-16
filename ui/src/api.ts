export interface Model {
  name: string;
  path: string;
  key: string;
  downloaded: boolean;
}
export interface Bootstrap {
  token: string;
  workspace: string;
  models: Model[];
}
export interface Voice {
  name: string;
  text: string;
  audio: string;
}
export interface Line {
  key: string;
  speaker: string;
  text: string;
  instruction?: string;
  gender: string;
  id?: string;
}
export interface Manifest {
  title: string;
  namespace: string;
  candidates: number;
  seed: number;
  lines: Line[];
  voice_library?: string;
  voices?: Record<string, unknown>;
}
export interface Document {
  path: string;
  hash: string;
  value: Manifest;
}
export interface Job {
  id: string;
  label: string;
  kind: string;
  status: string;
  log?: string;
  output: string;
  dialogue: string;
  title: string;
  destination?: string;
  download?: string;
}
export interface Take {
  id: string;
  fingerprint: string;
  gender: string;
  speaker: string;
  text: string;
  audio: string;
  candidate: number;
}
export interface Review {
  jobs: Take[];
  selected: string[];
  failures?: unknown[];
  export?: Job;
}
export const media = (path: string) =>
  "/api/media?path=" + encodeURIComponent(path);
let token = "";
export async function api<T>(route: string, data?: unknown): Promise<T> {
  const response = await fetch("/api/" + route, {
    method: data === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-Audio-Token": token },
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || response.statusText);
  if (route === "bootstrap") token = result.token;
  return result;
}
export type Action = (fn: () => Promise<unknown>) => void;
export type View =
  | "Dialogue"
  | "Review takes"
  | "Voice library"
  | "Voice Design"
  | "Models & setup";
