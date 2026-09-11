import { rebaseMapsDocument, type RebaseResult } from "./rebase";
import type { MapsDocument } from "./types";

export type MapsSaveAck = { document: MapsDocument; revision: number };
export type MapsSaveConflict = MapsSaveAck;

export type MapsSaveTransport = (document: MapsDocument, revision: number) => Promise<MapsSaveAck>;

export type MapsSaveQueueOptions = {
  document: () => MapsDocument | null;
  publish: (document: MapsDocument) => void;
  transport: MapsSaveTransport;
  onConflict: (conflict: { remote: MapsSaveAck; candidate: MapsDocument; paths: string[] }) => void;
  onError: (error: unknown) => void;
  onStatus?: (status: MapsSaveStatus) => void;
};

export type MapsSaveStatus = "saved" | "saving" | "unsaved" | "paused" | "error";

const copy = <T>(value: T): T => structuredClone(value);
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);

export class MapsSaveQueue {
  private base: MapsSaveAck | null = null;
  private inFlight: Promise<void> | null = null;
  private dirty = false;
  private blocked: { remote: MapsSaveAck; candidate: MapsDocument; paths: string[] } | null = null;
  private epoch = 0;
  private lastError = false;
  private lastStatus: MapsSaveStatus | null = null;

  constructor(private readonly options: MapsSaveQueueOptions) {}

  get status(): MapsSaveStatus {
    if (this.blocked) return "paused";
    if (this.inFlight) return "saving";
    if (this.lastError) return "error";
    if (this.dirty) return "unsaved";
    return "saved";
  }

  private emitStatus(): void {
    const status = this.status;
    if (status === this.lastStatus) return;
    this.lastStatus = status;
    this.options.onStatus?.(status);
  }

  setAcknowledged(ack: MapsSaveAck): void {
    this.base = { document: copy(ack.document), revision: ack.revision };
  }

  reset(ack: MapsSaveAck): void {
    this.epoch += 1;
    this.base = { document: copy(ack.document), revision: ack.revision };
    this.dirty = false;
    this.blocked = null;
    this.inFlight = null;
    this.lastError = false;
    this.emitStatus();
  }

  reconcile(ack: MapsSaveAck): void {
    const current = this.options.document();
    if (!this.base || !current) {
      this.setAcknowledged(ack);
      if (current) this.options.publish(copy(ack.document));
      return;
    }
    if (ack.revision < this.base.revision) return;
    this.applyMerge(rebaseMapsDocument(this.base.document, current, ack.document), ack);
  }

  markDirty(): void {
    this.dirty = true;
    this.emitStatus();
  }

  get conflict(): { remote: MapsSaveAck; candidate: MapsDocument; paths: string[] } | null {
    return this.blocked;
  }

  get revision(): number | null {
    return this.base?.revision ?? null;
  }

  flush(): Promise<void> {
    if (this.inFlight) return this.inFlight;
    if (this.blocked) return Promise.reject(new MapsSaveBlockedError());
    if (!this.dirty || !this.base) return Promise.resolve();
    const pending = this.drain();
    this.inFlight = pending;
    this.emitStatus();
    pending.then(
      () => { if (this.inFlight === pending) this.inFlight = null; this.emitStatus(); },
      () => { if (this.inFlight === pending) this.inFlight = null; this.emitStatus(); },
    );
    return pending;
  }

  reloadLatest(): void {
    if (!this.blocked) return;
    this.base = { document: copy(this.blocked.remote.document), revision: this.blocked.remote.revision };
    this.options.publish(copy(this.blocked.remote.document));
    this.blocked = null;
    this.dirty = false;
    this.emitStatus();
  }

  keepMyChanges(): Promise<void> {
    if (!this.blocked) return Promise.resolve();
    const conflict = this.blocked;
    this.base = { document: copy(conflict.remote.document), revision: conflict.remote.revision };
    this.options.publish(copy(conflict.candidate));
    this.blocked = null;
    this.dirty = true;
    this.emitStatus();
    return this.flush();
  }

  private applyMerge(result: RebaseResult<MapsDocument>, remote: MapsSaveAck): boolean {
    this.base = { document: copy(remote.document), revision: remote.revision };
    if (result.conflicts.length) {
      this.blocked = { remote: copy(remote), candidate: copy(result.value), paths: [...result.conflicts] };
      this.options.onConflict(this.blocked);
      this.emitStatus();
      return false;
    }
    this.options.publish(copy(result.value));
    this.dirty = !equal(result.value, remote.document);
    this.lastError = false;
    this.emitStatus();
    return true;
  }

  private async drain(): Promise<void> {
    const epoch = this.epoch;
    let retries = 0;
    while (this.dirty && !this.blocked) {
      const requestBase = this.base;
      const sent = this.options.document();
      if (!requestBase || !sent) return;
      this.dirty = false;
      try {
        const acknowledged = await this.options.transport(copy(sent), requestBase.revision);
        if (epoch !== this.epoch) return;
        if (this.base && acknowledged.revision < this.base.revision) {
          this.dirty = true;
          continue;
        }
        const latest = this.options.document() || sent;
        if (!this.applyMerge(rebaseMapsDocument(sent, latest, acknowledged.document), acknowledged)) throw new MapsSaveBlockedError();
        retries = 0;
      } catch (error) {
        if (epoch !== this.epoch) return;
        if (isConflict(error)) {
          const latest = this.options.document() || sent;
          if (!this.applyMerge(rebaseMapsDocument(requestBase.document, latest, error.remote.document), error.remote)) throw new MapsSaveBlockedError();
          if (retries++ >= 1) {
            this.lastError = true;
            this.options.onError(new Error("The map kept changing while it was being saved."));
            this.emitStatus();
            throw new Error("The map kept changing while it was being saved.");
          }
          continue;
        }
        this.dirty = true;
        this.lastError = true;
        this.options.onError(error);
        this.emitStatus();
        throw error;
      }
    }
  }
}

export class MapsSaveConflictError extends Error {
  constructor(readonly remote: MapsSaveConflict) {
    super("This map changed elsewhere.");
  }
}

export class MapsSaveBlockedError extends Error {
  constructor() {
    super("Resolve the map save conflict before continuing.");
  }
}

function isConflict(error: unknown): error is MapsSaveConflictError {
  return error instanceof MapsSaveConflictError;
}
