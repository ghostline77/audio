import { useEffect, useState } from "react";
import {
  api,
  media,
  type Action,
  type Job,
  type Review as Report,
  type Take,
} from "./api";
interface Props {
  jobs: Job[];
  active: string;
  choose: (path: string) => void;
  edit: (path: string) => void;
  act: Action;
}
export function Review({ jobs, active, choose, edit, act }: Props) {
  const [runs, setRuns] = useState<Job[]>([]),
    [report, setReport] = useState<Report | null>(null),
    [pending, setPending] = useState(false),
    [destination, setDestination] = useState("");
  const [error, setError] = useState("");
  const revision = jobs.map((j) => j.id + j.status).join(",");
  useEffect(() => {
    let live = true;
    act(async () => {
      const list = await api<Job[]>("runs");
      if (live) {
        setRuns(list);
        if (!active && list[0]) choose(list[0].output);
      }
    });
    return () => {
      live = false;
    };
  }, [revision, active]);
  const run = runs.find((r) => r.output === active);
  useEffect(() => {
    let live = true;
    setReport(null);
    setError("");
    if (active && run && run.status !== "running")
      act(async () => {
        try {
          const r = await api<Report>(
            "review?output=" + encodeURIComponent(active),
          );
          if (live) setReport(r);
        } catch (e) {
          if (live) setError(String(e));
        }
      });
    return () => {
      live = false;
    };
  }, [active, run?.status, revision]);
  const rows = new Map<string, Take[]>();
  for (const take of report?.jobs ?? []) {
    const key = take.id + "/" + take.gender;
    rows.set(key, [...(rows.get(key) ?? []), take]);
  }
  const locked = pending || jobs.some((j) => j.status === "running");
  async function select(t: Take) {
    if (!report) return;
    setPending(true);
    try {
      const siblings = rows.get(t.id + "/" + t.gender) ?? [];
      const selected = report.selected.filter(
        (f) => !siblings.some((s) => s.fingerprint === f),
      );
      selected.push(t.fingerprint);
      await api("selections", { output: active, fingerprints: selected });
      setReport({ ...report, selected, export: undefined });
    } finally {
      setPending(false);
    }
  }
  return (
    <section>
      <h1>{run?.title ?? "Review takes"}</h1>
      {runs.length > 0 && (
        <label>
          Previous generations
          <select
            disabled={pending}
            value={active}
            onChange={(e) => choose(e.target.value)}
          >
            {runs.map((r) => (
              <option key={r.output} value={r.output}>
                {r.title} · {r.status} · {r.output}
              </option>
            ))}
          </select>
        </label>
      )}
      {run && <button onClick={() => edit(run.dialogue)}>Edit dialogue</button>}
      {!run && <p>No generations yet.</p>}
      {run?.status === "running" && <p role="status">Generating takes…</p>}
      {error && <p role="alert">{error}</p>}
      {Boolean(report?.failures?.length) && (
        <p>Some lines failed. Completed takes are available below.</p>
      )}
      {[...rows].map(([key, takes]) => (
        <fieldset key={key}>
          <legend>{takes[0].speaker}</legend>
          <p>{takes[0].text}</p>
          {takes.map((t) => (
            <div key={t.fingerprint} className="flex gap-3 items-center">
              <label>
                <input
                  type="radio"
                  name={key}
                  disabled={locked}
                  checked={report!.selected.includes(t.fingerprint)}
                  onChange={() => act(() => select(t))}
                />{" "}
                Take {t.candidate}
              </label>
              <audio controls preload="none" src={media(t.audio)} />
            </div>
          ))}
        </fieldset>
      ))}
      {report && (
        <>
          <label>
            Destination folder (optional)
            <input
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
            />
          </label>
          <button
            disabled={locked || !report.selected.length}
            onClick={() =>
              act(async () => {
                setPending(true);
                try {
                  await api("export-dialogue", {
                    output: active,
                    fingerprints: report.selected,
                    destination,
                  });
                } finally {
                  setPending(false);
                }
              })
            }
          >
            Export {report.selected.length} selected lines
          </button>
          {report.export?.download && (
            <a
              href={
                "/api/download?path=" +
                encodeURIComponent(report.export.download)
              }
              download
            >
              Download selected WAVs
            </a>
          )}
        </>
      )}
    </section>
  );
}
