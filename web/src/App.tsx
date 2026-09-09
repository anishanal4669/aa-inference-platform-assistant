import { useEffect, useState } from "react";
import { useStream } from "./useStream";

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? "http://localhost:8080";

type Model = {
  id: string;
  description: string;
  context_window: number;
  max_output_tokens: number;
  pricing: { input_per_mtok: number; output_per_mtok: number };
};

const SAMPLES = [
  "Explain backpressure in a token streaming server to someone who knows HTTP but not ML.",
  "Write a haiku about a GPU at 3am.",
  "Give me three reasons speculative decoding can make throughput worse.",
];

export default function App() {
  const [models, setModels] = useState<Model[]>([]);
  const [modelId, setModelId] = useState("");
  const [prompt, setPrompt] = useState(SAMPLES[0]);
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(400);
  const [showRequest, setShowRequest] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const { text, live, usage, error, busy, send, stop } = useStream();

  useEffect(() => {
    fetch(`${GATEWAY}/v1/models`)
      .then((r) => r.json())
      .then((body) => {
        setModels(body.data);
        setModelId((current) => current || body.data[0]?.id || "");
      })
      .catch(() => setCatalogError("Can't reach the gateway. Is it running on " + GATEWAY + "?"));
  }, []);

  const model = models.find((m) => m.id === modelId);
  const cap = model?.max_output_tokens ?? 1000;

  // Server numbers win once the run finishes; live numbers fill the gap during it.
  const ttft = usage?.ttft_ms ?? live.ttftMs;
  const tokens = usage?.output_tokens ?? live.tokens;
  const tps = usage?.tokens_per_second || live.tps;
  const cost =
    usage?.cost_usd ??
    (model
      ? (Math.round(prompt.length / 4) / 1e6) * model.pricing.input_per_mtok +
        (live.tokens / 1e6) * model.pricing.output_per_mtok
      : 0);

  const peak = Math.max(12, ...live.trace);
  const points = live.trace
    .map((v, i) => `${(i / (live.trace.length - 1)) * 100},${44 - (v / peak) * 40}`)
    .join(" ");

  const curl = `curl -N ${GATEWAY}/v1/stream \\
  -H "authorization: Bearer $API_KEY" \\
  -H "content-type: application/json" \\
  -d '{
    "model": "${modelId}",
    "input": ${JSON.stringify(prompt.slice(0, 48) + (prompt.length > 48 ? "…" : ""))},
    "temperature": ${temperature},
    "max_tokens": ${maxTokens}
  }'`;

  function run() {
    if (busy) return stop();
    send({ model: modelId, input: prompt, temperature, max_tokens: Math.min(maxTokens, cap) });
  }

  return (
    <div className="pg">
      <header className="head">
        <h1 className="wordmark">Streaming playground</h1>
        <span className="endpoint mono">POST /v1/stream</span>
      </header>

      {catalogError && <div className="err">{catalogError}</div>}

      <div className="field">
        <textarea
          className="ta"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Send anything. Tokens come back as the model produces them."
        />
      </div>

      <div className="chips">
        {SAMPLES.map((s) => (
          <button key={s} className="chip" onClick={() => setPrompt(s)}>
            {s.split(" ").slice(0, 4).join(" ")}…
          </button>
        ))}
      </div>

      <div className="tiers">
        {models.map((m) => (
          <button
            key={m.id}
            className="tier mono"
            data-on={m.id === modelId ? "1" : "0"}
            title={m.description}
            onClick={() => {
              setModelId(m.id);
              setMaxTokens((t) => Math.min(t, m.max_output_tokens));
            }}
          >
            <b>{m.id}</b>
            <span>
              ${m.pricing.output_per_mtok}/M out · {Math.round(m.context_window / 1024)}K
            </span>
          </button>
        ))}
      </div>

      <div className="knobs">
        <div className="knob">
          <label htmlFor="temp">Temperature {temperature.toFixed(2)}</label>
          <input
            id="temp" type="range" min={0} max={1} step={0.05} value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
          />
        </div>
        <div className="knob">
          <label htmlFor="max">Max tokens {maxTokens}</label>
          <input
            id="max" type="range" min={64} max={cap} step={16} value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
          />
        </div>
      </div>

      <button className="run" data-stop={busy ? "1" : "0"} onClick={run} disabled={!prompt.trim() || !modelId}>
        {busy ? "Stop generating" : "Send prompt"}
      </button>

      <section className="bezel">
        <dl className="gauges">
          <div className="g">
            <dt>First token</dt>
            <dd className="mono">{ttft ? Math.round(ttft) : "—"}<i>ms</i></dd>
          </div>
          <div className="g">
            <dt>Throughput</dt>
            <dd className="mono">{tps ? tps.toFixed(1) : "—"}<i>t/s</i></dd>
          </div>
          <div className="g">
            <dt>Output</dt>
            <dd className="mono">{tokens || "—"}<i>tok</i></dd>
          </div>
          <div className="g">
            <dt>Cost</dt>
            <dd className="mono">${cost.toFixed(5)}</dd>
          </div>
        </dl>
        <svg className="trace" viewBox="0 0 100 44" preserveAspectRatio="none" aria-hidden="true">
          <polyline points={points} fill="none" stroke="#4130E8" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
          <line x1="0" y1="43" x2="100" y2="43" stroke="#333A46" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        </svg>
      </section>

      <div className="out" aria-live="polite">
        {text ? (
          <>{text}{busy && <span className="caret" />}</>
        ) : busy ? (
          <span className="caret" />
        ) : (
          <span className="empty">Response appears here, token by token.</span>
        )}
      </div>

      {error && <div className="err">{error}</div>}

      <div className="foot">
        <span>
          {usage
            ? `${usage.request_id} · finished ${usage.finish_reason} in ${Math.round(usage.duration_ms)}ms`
            : "Metrics are measured by the gateway, not estimated."}
        </span>
        <button className="link" onClick={() => setShowRequest((s) => !s)}>
          {showRequest ? "Hide request" : "View request"}
        </button>
      </div>

      {showRequest && <pre className="curl mono">{curl}</pre>}
    </div>
  );
}
