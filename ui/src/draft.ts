import { api, type Document, type Manifest } from "./api";

// Each queued write uses the hash returned by the previous successful write.
export class Draft {
  revision = 0;
  saved = 0;
  private queue = Promise.resolve();
  constructor(public doc: Document) {}
  edit(value: Manifest) {
    this.doc = { ...this.doc, value };
    this.revision++;
  }
  flush() {
    const write = async () => {
      while (this.saved !== this.revision) {
        const revision = this.revision;
        const result = await api<Document>("manifest", this.doc);
        const ids = new Map(
          result.value.lines.map((line) => [line.key, line.id]),
        );
        this.doc = {
          ...this.doc,
          hash: result.hash,
          value: {
            ...this.doc.value,
            lines: this.doc.value.lines.map((line) => ({
              ...line,
              id: line.id ?? ids.get(line.key),
            })),
          },
        };
        this.saved = revision;
      }
    };
    this.queue = this.queue.catch(() => {}).then(write);
    return this.queue;
  }
}
