import { useCallback, useRef, useState } from "react";

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? "http://localhost:8080";
const API_KEY = import.meta.env.VITE_API_KEY ?? "sk-demo";

export type Usage = {
  request_id: string;
  input_tokens: number;
  output_tokens: number;
  ttft_ms: number | null;
  duration_ms: number;
  tokens_per_second: number;
  cost_usd: number;
  finish_reason: string;
};

export type StreamParams = {
  model: string;
  input: string;
  temperature: number;
  max_tokens: number;
};

/** Live client-side view of the stream, recomputed as frames land. */
export type Live = {
  ttftMs: number | null;
  tokens: number;
  tps: number;
  trace: number[];
};

const EMPTY: Live = { ttftMs: null, tokens: 0, tps: 0, trace: new Array(48).fill(0) };

export function useStream() {
  const [text, setText] = useState("");
  const [live, setLive] = useState<Live>(EMPTY);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const send = useCallback(async (params: StreamParams) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setText("");
    setUsage(null);
    setError(null);
    setLive(EMPTY);
    setBusy(true);

    const started = performance.now();
    let acc = "";
    let sampledAt = started;
    let sampledTokens = 0;

    // The server reports authoritative counts at the end; until then this is
    // the same 4-chars-per-token heuristic the gateway uses.
    const onText = (chunk: string) => {
      acc += chunk;
      setText(acc);
      const now = performance.now();
      const tokens = Math.max(1, Math.round(acc.length / 4));
      const elapsed = (now - started) / 1000;
      setLive((prev) => {
        let trace = prev.trace;
        if (now - sampledAt > 120) {
          const rate = (tokens - sampledTokens) / ((now - sampledAt) / 1000);
          sampledAt = now;
          sampledTokens = tokens;
          trace = [...prev.trace.slice(1), Math.max(0, rate)];
        }
        return {
          ttftMs: prev.ttftMs ?? now - started,
          tokens,
          tps: elapsed > 0 ? tokens / elapsed : 0,
          trace,
        };
      });
    };

    try {
      const res = await fetch(`${GATEWAY}/v1/stream`, {
        method: "POST",
        signal: ac.signal,
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${API_KEY}`,
        },
        body: JSON.stringify(params),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail ?? `Gateway returned ${res.status}`);
      }
      if (!res.body) throw new Error("This browser cannot read streaming responses.");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Frames are separated by a blank line; keep any partial tail.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          let name = "message";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) name = line.slice(7).trim();
            else if (line.startsWith("data: ")) data += line.slice(6);
            // lines starting with ':' are heartbeats — ignore them
          }
          if (!data) continue;
          const payload = JSON.parse(data);
          if (name === "delta") onText(payload.text);
          else if (name === "usage") setUsage(payload as Usage);
          else if (name === "error") throw new Error(payload.message);
        }
      }
    } catch (err) {
      const e = err as Error;
      if (e.name !== "AbortError") setError(e.message);
    } finally {
      setBusy(false);
      setLive((prev) => ({ ...prev, trace: [...prev.trace.slice(1), 0] }));
      abortRef.current = null;
    }
  }, []);

  return { text, live, usage, error, busy, send, stop };
}
