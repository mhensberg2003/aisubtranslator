# OpenRouter routing is pinned rather than left to fail over

We reach the model through OpenRouter so the provider is a configuration string
rather than a code change. But OpenRouter's default behaviour — routing to
whichever upstream is available — interacts badly with two things this pipeline
depends on. Structured-output enforcement varies between upstreams serving the
same model, and prompt caching is per-upstream, so a mid-job failover silently
re-pays full input price for the Bible and system prompt on every remaining
Chunk. We therefore set `require_parameters: true` and pin to the first-party
upstream, accepting that an outage fails the run.

## Consequences

A whole Job now behaves consistently: one upstream, one cache, one set of schema
guarantees, predictable cost. When the upstream is unavailable the run stops
with an error instead of continuing more expensively and less strictly, which is
the correct failure for a resumable batch job — Jobs are checkpointed, so
resuming later costs nothing already paid for.

This is deliberately the opposite of what a latency-sensitive service would do,
and a reader who assumes availability is the priority will want to remove the
pin. It is there for determinism, not reliability.
