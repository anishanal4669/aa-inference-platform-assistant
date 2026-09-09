# Inference gateway + streaming playground

A working end-to-end slice of an inference platform: a FastAPI gateway that
streams tokens over SSE with real metering, and a React playground that shows
time-to-first-token and throughput as they happen.

It runs with no GPU and no API key. The default catalog uses a local `echo`
backend, so you can start the stack, watch tokens stream, cancel mid-generation
and see billing land — then repoint a tier at vLLM or a hosted provider without
touching the frontend.

```
web (Vite/React)  ──POST /v1/stream──▶  gateway (FastAPI)  ──▶  provider adapter
     SSE reader   ◀──event: delta───┘   auth · limits · metering    ├─ openai-compatible (vLLM, TGI, Ollama)
                                                                    ├─ anthropic
                                                                    └─ echo (no dependencies)
```

## Run it

```bash
cd server && pip install -r requirements-dev.txt && uvicorn app.main:app --port 8080
cd web && npm install && npm run dev      # http://localhost:5173
```

Or `docker compose up --build`. Tests: `cd server && pytest -q`.

## The wire format

`POST /v1/stream` returns `text/event-stream`. Five event types, all JSON:

| event | payload | when |
|---|---|---|
| `start` | `{request_id, model}` | immediately, before any model work lands |
| `delta` | `{text}` | once per chunk the upstream produces |
| `usage` | token counts, `ttft_ms`, `tokens_per_second`, `cost_usd` | after the last delta |
| `done` | `{request_id}` | terminal, success |
| `error` | `{type, message}` | terminal, mid-stream failure |

Lines beginning with `:` are heartbeats. Clients ignore them; they exist so
idle proxies don't drop a long connection.

```bash
curl -N localhost:8080/v1/stream \
  -H "authorization: Bearer sk-demo" \
  -H "content-type: application/json" \
  -d '{"model":"core-70b","input":"why is TTFT the metric that matters?","max_tokens":200}'
```

Also available: `GET /v1/models` (catalog and pricing), `GET /v1/usage`
(per-key ledger), `GET /healthz`.

## Decisions worth knowing about

**Upstream failures are HTTP failures.** The first chunk is pulled before the
`StreamingResponse` is constructed, so a dead backend returns 502 rather than a
200 with an error hidden in the body. Anything that breaks after that point can
only be an `error` event, since the status line is already on the wire.

**Disconnects still bill.** If the client hangs up, the generator is closed, the
upstream connection is torn down, and whatever was produced is written to the
ledger with `finish_reason: "cancelled"`. Try it: `curl --max-time 0.5 ...` and
watch the gateway log.

**Heartbeats never interrupt a read.** `asyncio.wait_for` would cancel an
in-flight `__anext__` on timeout and corrupt the HTTP stream, so `sse.py` holds
the pending read across timeouts instead.

**Token counts come from the upstream when offered.** vLLM's
`stream_options.include_usage` and Anthropic's `message_delta` both report real
counts; the 4-chars-per-token heuristic is only a placeholder until they arrive.
Swap in the served model's tokenizer before you bill anyone on it.

**Rate limits reserve, then refund.** A request reserves prompt + max_tokens up
front and returns the unused remainder when the stream ends, so a large
`max_tokens` can't be used to sidestep the per-minute budget.

## Pointing a tier at a real model

Edit `server/app/registry.py` (or set `GATEWAY_MODELS_FILE` to a JSON array):

```python
ModelSpec(
    id="core-70b",
    provider="openai",                                # was "echo"
    upstream_model="meta-llama/Llama-3.3-70B-Instruct",
    input_price_per_mtok=0.55,
    output_price_per_mtok=2.20,
)
```

Then start vLLM and point the gateway at it:

```bash
vllm serve meta-llama/Llama-3.3-70B-Instruct --port 8000
export GATEWAY_OPENAI_BASE_URL=http://localhost:8000/v1
```

The `anthropic` provider works the same way with `GATEWAY_ANTHROPIC_API_KEY`.
Adding a third backend means one file in `app/providers/` yielding `TextDelta`
and `UpstreamUsage`, plus an entry in the `_PROVIDERS` map.

## Before this goes near production

- Set `GATEWAY_ALLOW_ANONYMOUS=false` and store hashed keys in a database.
- Move the limiter and ledger to Redis and a real warehouse — both are
  in-process today, which is why the container runs a single worker.
- Disable proxy buffering end to end. The gateway sends
  `x-accel-buffering: no`, but a CDN or load balancer in front of it will still
  happily buffer your stream and destroy TTFT.
- Add queue-depth and GPU-utilisation metrics; TTFT under load is a queueing
  property, not a model property.
