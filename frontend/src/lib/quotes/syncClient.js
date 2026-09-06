/**
 * syncClient.js — the websocket resync state machine, ARCHITECTURE §14.3.
 *
 * Ported verbatim from an earlier syncClient.ts. The logic is unchanged; only
 * the type annotations are gone, replaced by JSDoc. The stack is JavaScript
 * only, and a single .ts file fails the build check.
 *
 * The rule this enforces: if an incoming delta's sequence number is not exactly
 * the one expected, drop it, enter RE_SYNCING and ask the server for a fresh
 * snapshot. Applying a delta across a gap silently corrupts local state, and a
 * quietly wrong price is worse than a visible resync.
 */

/** @typedef {"CONNECTING"|"SYNCED"|"RE_SYNCING"} SyncClientState */

/**
 * @template {{symbol: string}} T
 * @typedef {object} StreamFrameEnvelope
 * @property {"SNAPSHOT"|"DELTA"|"RESYNC"|"HEARTBEAT"} type
 * @property {number} seq
 * @property {string} as_of
 * @property {T[]} quotes
 */

export class StreamingSyncClient {
  constructor() {
    /** @type {SyncClientState} */
    this.state = "CONNECTING";
    this.expectedSeq = 0;
    /** @type {Map<string, object>} */
    this.store = new Map();
    this.discardedDeltaCount = 0;
  }

  /**
   * @param {StreamFrameEnvelope<object>} frame
   * @returns {"resync"|null} "resync" when the caller must request a snapshot
   */
  handleMessage(frame) {
    if (frame.type === "SNAPSHOT") {
      this.store = new Map(frame.quotes.map((quote) => [quote.symbol, quote]));
      this.expectedSeq = frame.seq + 1;
      this.state = "SYNCED";
      return null;
    }
    if (frame.type !== "DELTA") return null;
    if (this.state === "RE_SYNCING") {
      this.discardedDeltaCount += 1;
      return null;
    }
    if (frame.seq < this.expectedSeq) return null;
    if (frame.seq > this.expectedSeq) {
      this.state = "RE_SYNCING";
      this.discardedDeltaCount += 1;
      return "resync";
    }
    frame.quotes.forEach((quote) => this.store.set(quote.symbol, quote));
    this.expectedSeq += 1;
    return null;
  }
}
