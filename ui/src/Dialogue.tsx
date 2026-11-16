import { useEffect, useRef, useState } from "react";
import {
  api,
  type Action,
  type Bootstrap,
  type Document,
  type Job,
  type Line,
  type Manifest,
  type Voice,
  type View,
} from "./api";
import { Draft } from "./draft";

interface Props {
  boot: Bootstrap;
  voices: Voice[];
  busy: boolean;
  act: Action;
  navigate: (view: View) => void;
  generated: (job: Job) => void;
  requestedPath?: { path: string };
}
const emptyLine = (): Line => ({
  key: "line-" + crypto.randomUUID(),
  speaker: "",
  text: "",
  gender: "shared",
});
const lastKey = "ghostline-audio-last-dialogue";

export function Dialogue({
  boot,
  voices,
  busy,
  act,
  navigate,
  generated,
  requestedPath,
}: Props) {
  const draft = useRef<Draft | null>(null);
  const [version, render] = useState(0);
  const [status, setStatus] = useState("");
  const [list, setList] = useState<
    { path: string; title: string; lines: number }[]
  >([]);
  const [selected, select] = useState("");
  const [title, setTitle] = useState("");
  const [importPath, setImportPath] = useState("");
  const models = boot.models.filter((m) => m.key !== "design");
  const [checkpoint, setCheckpoint] = useState(
    (models.find((m) => m.downloaded) ?? models[0])?.path ?? "",
  );
  const doc = draft.current?.doc;
  const value = doc?.value;
  const refresh = async () => {
    const rows = await api<typeof list>("dialogues");
    setList(rows);
    select((old) =>
      rows.some((r) => r.path === old) ? old : (rows[0]?.path ?? ""),
    );
  };
  async function flush() {
    const current = draft.current;
    if (!current) return;
    await current.flush();
    if (current === draft.current) {
      setStatus(
        current.saved === current.revision
          ? "Saved automatically"
          : "Saving changes…",
      );
      render((v) => v + 1);
    }
  }
  async function open(load: () => Promise<Document>) {
    await flush();
    const result = await load();
    draft.current = new Draft(result);
    localStorage.setItem(lastKey, result.path);
    setStatus("Saved automatically");
    render((v) => v + 1);
    await refresh();
  }
  const openPath = (path: string) =>
    open(() => api<Document>("dialogue?path=" + encodeURIComponent(path)));
  useEffect(() => {
    act(async () => {
      await refresh();
      const last = localStorage.getItem(lastKey);
      if (last)
        try {
          await openPath(last);
        } catch (error) {
          localStorage.removeItem(lastKey);
          throw error;
        }
    });
  }, []);
  useEffect(() => {
    if (requestedPath) act(() => openPath(requestedPath.path));
  }, [requestedPath]);
  useEffect(() => {
    function unload(e: BeforeUnloadEvent) {
      if (draft.current && draft.current.revision !== draft.current.saved) {
        e.preventDefault();
        e.returnValue = "";
      }
    }
    function key(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        act(flush);
      }
    }
    addEventListener("beforeunload", unload);
    addEventListener("keydown", key);
    return () => {
      removeEventListener("beforeunload", unload);
      removeEventListener("keydown", key);
    };
  }, []);
  useEffect(() => {
    const current = draft.current;
    if (!current || current.saved === current.revision) return;
    const timer = setTimeout(
      () =>
        act(async () => {
          try {
            await flush();
          } catch (error) {
            setStatus("Save failed");
            throw error;
          }
        }),
      800,
    );
    return () => clearTimeout(timer);
  }, [version]);
  function edit(partial: Partial<Manifest>) {
    const current = draft.current;
    if (!current) return;
    current.edit({ ...current.doc.value, ...partial });
    setStatus("Saving changes…");
    render((v) => v + 1);
  }
  function editLine(index: number, partial: Partial<Line>) {
    if (value)
      edit({
        lines: value.lines.map((line, i) =>
          i === index ? { ...line, ...partial } : line,
        ),
      });
  }
  if (!value || !doc)
    return (
      <section>
        <h1>Dialogue</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              await open(() => api("new-dialogue", { title }));
              edit({ lines: [emptyLine()] });
              await flush();
            });
          }}
        >
          <label>
            Dialogue name
            <input
              required
              maxLength={100}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <button>Create dialogue</button>
        </form>
        <label>
          Saved dialogues
          <select value={selected} onChange={(e) => select(e.target.value)}>
            {list.map((row) => (
              <option key={row.path} value={row.path}>
                {row.title} · {row.lines} lines
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={!selected}
          onClick={() => act(() => openPath(selected))}
        >
          Open dialogue
        </button>
        <label>
          Import dialogue JSON
          <input
            type="file"
            accept=".json"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file)
                act(() =>
                  open(async () =>
                    api("import-dialogue", {
                      filename: file.name,
                      text: await file.text(),
                    }),
                  ),
                );
            }}
          />
        </label>
        <details>
          <summary>Import from a workspace path</summary>
          <input
            aria-label="Existing JSON file"
            value={importPath}
            onChange={(e) => setImportPath(e.target.value)}
          />
          <button
            disabled={!importPath}
            onClick={() =>
              act(() =>
                open(() => api("import-dialogue", { path: importPath })),
              )
            }
          >
            Import existing file
          </button>
        </details>
      </section>
    );
  const ready =
    models.find((m) => m.path === checkpoint)?.downloaded ??
    Boolean(checkpoint);
  const incomplete = value.lines.findIndex((l) => !l.speaker || !l.text.trim());
  const count = value.lines.length * (value.candidates || 1);
  return (
    <section>
      <div className="flex justify-between">
        <h1>{value.title || "Imported dialogue"}</h1>
        <button
          onClick={() =>
            act(async () => {
              await flush();
              draft.current = null;
              localStorage.removeItem(lastKey);
              render((v) => v + 1);
              await refresh();
            })
          }
        >
          All dialogues
        </button>
      </div>
      <p role="status">{status}</p>
      <button onClick={() => navigate("Voice library")}>Preview cast</button>
      {value.lines.map((line, i) => (
        <article key={line.key}>
          <h2>Line {i + 1}</h2>
          <button
            onClick={() =>
              edit({ lines: value.lines.filter((_, idx) => idx !== i) })
            }
          >
            Remove line {i + 1}
          </button>
          <label>
            Voice for line {i + 1}
            <select
              value={line.speaker}
              onChange={(e) =>
                editLine(i, {
                  speaker: e.target.value,
                  gender:
                    e.target.value === "V Female"
                      ? "female"
                      : e.target.value === "V Male"
                        ? "male"
                        : "shared",
                })
              }
            >
              <option value="">Choose a voice…</option>
              {[
                ...new Set(
                  [
                    ...(value.voice_library ? voices.map((v) => v.name) : []),
                    ...Object.keys(value.voices ?? {}),
                    line.speaker,
                  ].filter(Boolean),
                ),
              ].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Dialogue line {i + 1}
            <textarea
              value={line.text}
              onChange={(e) => editLine(i, { text: e.target.value })}
            />
          </label>
          <details>
            <summary>Delivery &amp; game binding</summary>
            <label>
              Delivery instruction
              <input
                value={line.instruction ?? ""}
                onChange={(e) =>
                  editLine(i, { instruction: e.target.value || undefined })
                }
              />
            </label>
            <label>
              Audio variant
              <select
                value={line.gender}
                onChange={(e) => editLine(i, { gender: e.target.value })}
              >
                {["shared", "female", "male"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
          </details>
        </article>
      ))}
      <button onClick={() => edit({ lines: [...value.lines, emptyLine()] })}>
        Add line
      </button>
      <label>
        Takes per line
        <select
          value={value.candidates || 1}
          onChange={(e) => edit({ candidates: +e.target.value })}
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
      </label>
      <details>
        <summary>Generation settings</summary>
        <label>
          Voice model
          <select
            value={checkpoint}
            onChange={(e) => setCheckpoint(e.target.value)}
          >
            {models.map((m) => (
              <option key={m.path} value={m.path}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Local checkpoint folder
          <input
            value={checkpoint}
            onChange={(e) => setCheckpoint(e.target.value)}
          />
        </label>
        <label>
          Random seed
          <input
            type="number"
            value={value.seed || 0}
            onChange={(e) => edit({ seed: +e.target.value })}
          />
        </label>
      </details>
      {!ready && (
        <button onClick={() => navigate("Models & setup")}>
          Set up a voice model
        </button>
      )}
      {incomplete >= 0 && (
        <p>Choose a voice and enter text for line {incomplete + 1}.</p>
      )}
      <button
        disabled={!count || !ready || busy || incomplete >= 0}
        onClick={() =>
          act(async () => {
            await flush();
            const saved = draft.current!.doc;
            generated(
              await api<Job>("generate-dialogue", {
                path: saved.path,
                hash: saved.hash,
                checkpoint,
              }),
            );
          })
        }
      >
        Generate {count} takes
      </button>
      <details>
        <summary>File &amp; localization details</summary>
        <label>
          Rename dialogue
          <input
            maxLength={100}
            value={value.title ?? ""}
            onChange={(e) => edit({ title: e.target.value })}
          />
        </label>
        <label>
          Localization namespace
          <input readOnly value={value.namespace} />
        </label>
        <p>{doc.path}</p>
        <textarea
          aria-label="Generated dialogue JSON"
          readOnly
          rows={8}
          value={JSON.stringify(value, null, 2)}
        />
        <button
          onClick={() =>
            act(async () => {
              await flush();
              const url = URL.createObjectURL(
                new Blob([JSON.stringify(draft.current!.doc.value, null, 2)], {
                  type: "application/json",
                }),
              );
              const a = document.createElement("a");
              a.href = url;
              a.download = doc.path.split(/[\\/]/).pop()!;
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 1000);
            })
          }
        >
          Download dialogue JSON
        </button>
      </details>
    </section>
  );
}
