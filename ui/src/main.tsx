import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  api,
  media,
  type Bootstrap,
  type Job,
  type View,
  type Voice,
} from "./api";
import { Dialogue } from "./Dialogue";
import { Review } from "./Review";
import { Comparison } from "./Comparison";
import "./style.css";

function Workbench() {
  const [boot, setBoot] = useState<Bootstrap>(),
    [voices, setVoices] = useState<Voice[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [view, navigate] = useState<View>("Dialogue"),
    [message, notify] = useState(""),
    [active, choose] = useState(""),
    [requested, setRequested] = useState<{ path: string }>(),
    [query, search] = useState(""),
    [path, setPath] = useState("work/design/reference.wav"),
    [preview, setPreview] = useState("");
  const act = useCallback((fn: () => Promise<unknown>) => {
    void fn().catch((e) => notify(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(() => {
    let live = true,
      timer: ReturnType<typeof setTimeout>,
      last = "";
    async function poll() {
      try {
        const list = await api<Job[]>("jobs");
        if (!live) return;
        setJobs(list);
        const stamp = list.map((j) => j.id + j.status).join(",");
        if (stamp !== last) {
          const data = await api<Bootstrap>("bootstrap");
          if (live) setBoot(data);
          last = stamp;
        }
      } catch (e) {
        if (live) notify(String(e));
      } finally {
        if (live) timer = setTimeout(poll, 1500);
      }
    }
    act(async () => {
      const data = await api<Bootstrap>("bootstrap"),
        cast = await api<Voice[]>("voices");
      if (live) {
        setBoot(data);
        setVoices(cast);
        void poll();
      }
    });
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);
  const busy = jobs.some((j) => j.status === "running"),
    latest = jobs.at(-1);
  return (
    <main>
      <header>
        <strong>Ghostline Audio</strong>
        <span>{boot?.workspace}</span>
      </header>
      <nav>
        {(
          [
            "Dialogue",
            "Review takes",
            "Voice library",
            "Voice Design",
            "Models & setup",
          ] as View[]
        ).map((v) => (
          <button
            aria-current={view === v ? "page" : undefined}
            key={v}
            onClick={() => navigate(v)}
          >
            {v}
          </button>
        ))}
      </nav>
      {message && (
        <p role="alert">
          {message} <button onClick={() => notify("")}>Dismiss</button>
        </p>
      )}
      {!boot ? (
        <p>Connecting…</p>
      ) : (
        <>
          <div hidden={view !== "Dialogue"}>
            <Dialogue
              boot={boot}
              voices={voices}
              busy={busy}
              act={act}
              navigate={navigate}
              requestedPath={requested}
              generated={(job) => {
                choose(job.output);
                setJobs((old) => [...old, job]);
                navigate("Review takes");
              }}
            />
          </div>
          <div hidden={view !== "Review takes"}>
            <Review
              jobs={jobs}
              active={active}
              choose={choose}
              act={act}
              edit={(p) => {
                setRequested({ path: p });
                navigate("Dialogue");
              }}
            />
          </div>
          <section hidden={view !== "Voice library"}>
            <h1>Voice library</h1>
            <label>
              Find a character
              <input
                type="search"
                value={query}
                onChange={(e) => search(e.target.value)}
              />
            </label>
            <div className="grid gap-3 md:grid-cols-2">
              {voices
                .filter((v) =>
                  v.name.toLowerCase().includes(query.toLowerCase()),
                )
                .map((v) => (
                  <article key={v.name}>
                    <h2>{v.name}</h2>
                    <p>{v.text}</p>
                    <audio controls preload="none" src={media(v.audio)} />
                  </article>
                ))}
            </div>
          </section>
          <section hidden={view !== "Voice Design"}>
            <h1>Voice Design</h1>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const data = Object.fromEntries(new FormData(e.currentTarget));
                act(async () => {
                  await api("design", data);
                  setPath(String(data.output));
                  notify("Voice generation started.");
                });
              }}
            >
              {Object.entries({
                speaker: ["NPC name", ""],
                checkpoint: [
                  "VoiceDesign checkpoint",
                  boot.models.find((m) => m.key === "design")?.path ?? "",
                ],
                language: ["Language", "English"],
                seed: ["Seed", "42"],
                output: ["Output WAV", "work/design/reference.wav"],
              }).map(([k, [label, value]]) => (
                <label key={k}>
                  {label}
                  <input
                    required
                    name={k}
                    defaultValue={value}
                    type={k === "seed" ? "number" : "text"}
                  />
                </label>
              ))}
              <label>
                Voice description
                <textarea required name="description" />
              </label>
              <label>
                Reference text
                <textarea required name="text" />
              </label>
              <button disabled={busy}>Generate reference</button>
            </form>
            <label>
              Design WAV
              <input value={path} onChange={(e) => setPath(e.target.value)} />
            </label>
            <button
              onClick={() => setPreview(media(path) + "&v=" + Date.now())}
            >
              Load preview
            </button>
            {preview && (
              <audio
                controls
                src={preview}
                onError={() =>
                  notify(
                    "Preview unavailable. Check the WAV path and generation status.",
                  )
                }
              />
            )}
            <button
              onClick={() =>
                act(async () => {
                  await api("adopt", { audio: path });
                  setVoices(await api<Voice[]>("voices"));
                  notify("Library voice saved.");
                })
              }
            >
              Use as NPC voice
            </button>
          </section>
          <section hidden={view !== "Models & setup"}>
            <h1>Models &amp; setup</h1>
            {boot.models.map((m) => (
              <article key={m.key}>
                <a href={"https://huggingface.co/" + m.name}>{m.name}</a>
                <p>{m.path}</p>
                <button
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await api("download", { model: m.key });
                      notify("Download started.");
                    })
                  }
                >
                  {m.downloaded
                    ? "Resume / verify download"
                    : "Download checkpoint"}
                </button>
              </article>
            ))}
          </section>
        </>
      )}
      {latest && (
        <details open>
          <summary>
            Activity · {latest.label} · {latest.status}
          </summary>
          <pre>{latest.log}</pre>
        </details>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  location.pathname === "/comparisons" ? <Comparison /> : <Workbench />,
);
