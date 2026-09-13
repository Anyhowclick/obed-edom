/** Serialises every asynchronous admin-0/admin-1 mutation on one map against a single
 * generation counter, so overlay painting, the highlight effect and camera-driven region syncs
 * can never apply out of order.
 *
 * A style load (`beginStyleLoad`) owns the map until it finishes: it installs the admin/church
 * sources from scratch, so aborting it half-way would leave the map without the sources the
 * other paths need. Syncs that arrive while it is in flight are therefore deferred rather than
 * superseding it — `endStyleLoad` reports whether such work must be replayed. Outside a style
 * load, `beginSync` increments the generation, invalidating any older in-flight request. The
 * replay is discharged by the highlight effect, whose `needed` set must stay a superset of the
 * camera sync's. */
export class AdminSyncGate {
  private generation = 0;
  private styleToken: number | null = null;
  private pending = false;
  private replayOwed = false;
  private inFlight = 0;
  private waiters: Array<() => void> = [];

  beginStyleLoad(): number {
    this.styleToken = ++this.generation;
    return this.styleToken;
  }

  /** Clears the in-flight marker when `token` is the newest style load, and reports whether
   * deferred sync work should now be replayed. An older, slower load clears nothing. */
  endStyleLoad(token: number): boolean {
    if (this.styleToken !== token) return false;
    this.styleToken = null;
    const replay = this.pending;
    this.pending = false;
    this.replayOwed = replay;
    this.flush();
    return replay;
  }

  /** Drops an owed replay the highlight effect cannot discharge, e.g. when the style carries no
   * `admin0` source to sync. */
  clearReplay(): void {
    this.replayOwed = false;
    this.flush();
  }

  /** The generation for a highlight/camera sync, or `null` when a style load is in flight and
   * the caller must defer to the replay instead. */
  beginSync(): number | null {
    this.replayOwed = false;
    if (this.styleToken !== null) {
      this.pending = true;
      return null;
    }
    return ++this.generation;
  }

  isCurrent(token: number): boolean {
    return this.generation === token;
  }

  /** Counts `work` as an in-flight sync, so `settled()` cannot resolve while it runs. */
  track<T>(work: Promise<T>): Promise<T> {
    this.inFlight += 1;
    return work.finally(() => {
      this.inFlight -= 1;
      this.flush();
    });
  }

  /** Resolves once no style load is in flight, no deferred replay is owed and no tracked sync is
   * running — i.e. the map's admin overlays reflect the latest request. */
  settled(): Promise<void> {
    if (this.isIdle()) return Promise.resolve();
    return new Promise((resolve) => {
      this.waiters.push(resolve);
    });
  }

  private isIdle(): boolean {
    return this.styleToken === null && !this.pending && !this.replayOwed && this.inFlight === 0;
  }

  private flush(): void {
    if (!this.isIdle()) return;
    const waiters = this.waiters;
    this.waiters = [];
    for (const resolve of waiters) resolve();
  }
}
