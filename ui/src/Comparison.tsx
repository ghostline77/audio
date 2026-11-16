import { useEffect, useState } from "react";
import { api, media } from "./api";
interface Source {
  text: string;
  original: string;
  id: string;
  depot: string;
  signal: { rate: number; clipped_samples: number };
  scene_evidence: { event_node: string };
}
interface Item {
  label: string;
  actor: string;
  number: number;
  mission: string;
  context: string;
  reference_text: string;
  previous_reference_text: string;
  reference_audio: string;
  new_sample: string;
  previous_reference_audio: string;
  previous_sample: string;
  sources: Source[];
  source_url: string;
}
interface Manifest {
  title: string;
  target_text: string;
  note: string;
  selected_candidates?: Record<string, number>;
  items: Item[];
}
function Player({ label, path }: { label: string; path: string }) {
  return (
    <div>
      <p>{label}</p>
      <audio controls preload="none" src={media(path)} />
    </div>
  );
}
export function Comparison() {
  const [data, setData] = useState<Manifest>(),
    [actor, setActor] = useState("All"),
    [error, setError] = useState("");
  useEffect(() => {
    const path = new URLSearchParams(location.search).get("path");
    if (!path) {
      setError("A comparison manifest path is required");
      return;
    }
    api<{ value: Manifest }>("manifest?path=" + encodeURIComponent(path))
      .then((r) => setData(r.value))
      .catch((e) => setError(String(e)));
  }, []);
  return (
    <main>
      <a href="/">Ghostline Audio</a>
      <h1>{data?.title ?? (error || "Loading comparisons…")}</h1>
      {data && (
        <>
          <p>{data.target_text}</p>
          <p>
            {data.selected_candidates
              ? Object.entries(data.selected_candidates)
                  .map(([k, v]) => k + " " + v)
                  .join(" · ")
              : "No candidates selected."}
          </p>
          <label>
            Actor
            <select value={actor} onChange={(e) => setActor(e.target.value)}>
              {["All", ...new Set(data.items.map((i) => i.actor))].map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
          {data.items
            .filter((i) => actor === "All" || i.actor === actor)
            .map((i) => (
              <article key={i.actor + i.number}>
                <h2>
                  {i.label}
                  {data.selected_candidates?.[i.actor] === i.number
                    ? " · Selected"
                    : ""}
                </h2>
                <p>
                  {i.mission} — {i.context}
                </p>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h3>New reference</h3>
                    <p>{i.reference_text}</p>
                    <Player label="Reference" path={i.reference_audio} />
                    <Player label="Generated comparison" path={i.new_sample} />
                  </div>
                  <div>
                    <h3>Earlier reference</h3>
                    <p>{i.previous_reference_text}</p>
                    <Player
                      label="Reference"
                      path={i.previous_reference_audio}
                    />
                    <Player
                      label="Regenerated comparison"
                      path={i.previous_sample}
                    />
                  </div>
                </div>
                <details>
                  <summary>Original exports &amp; provenance</summary>
                  {i.sources.map((s) => (
                    <div key={s.id}>
                      <p>{s.text}</p>
                      <Player
                        label={"Original recording · " + s.signal.rate + " Hz"}
                        path={s.original}
                      />
                      <p>
                        {s.id} · {s.depot} · scene event{" "}
                        {s.scene_evidence.event_node} ·{" "}
                        {s.signal.clipped_samples} clipped samples
                      </p>
                    </div>
                  ))}
                  <a href={i.source_url} rel="noreferrer" target="_blank">
                    Mission context
                  </a>
                </details>
              </article>
            ))}
          <p>{data.note}</p>
        </>
      )}
    </main>
  );
}
