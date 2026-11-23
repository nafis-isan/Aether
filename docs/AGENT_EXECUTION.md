# Goal-oriented agent execution

Aether routes a request to one worker, creates a persisted plan for multi-action
goals, and executes the plan sequentially. The next step receives earlier step
results as context. Progress is written to run checkpoints and emitted as
`plan.created`, `plan.step.started`, and `plan.step.completed` events. The
workspace displays that event-derived progress and offers a stop control.

Single-action requests use a one-step plan without an extra planning request.
Multi-action requests get a structured plan from the selected model. Plans are
bounded by `AGENT_MAX_PLAN_STEPS` and are not treated as proof that any step
actually succeeded; only completed step results and tool events indicate
execution.

## Execution limits

The `.env.example` values are conservative defaults:

| Setting | Default | Purpose |
|---|---:|---|
| `AGENT_MAX_PLAN_STEPS` | 5 | Maximum planned actions |
| `AGENT_MAX_TOOL_CALLS` | 5 | Maximum tools executed in one run |
| `AGENT_MAX_MODEL_CALLS` | 10 | Maximum provider completions in one run |
| `AGENT_MAX_RUN_SECONDS` | 120 | Maximum active execution time per run attempt |
| `AGENT_MAX_COMPLETION_TOKENS` | 1200 | Upper bound requested for each model completion |
| `AGENT_MAX_CONTEXT_CHARS` | 40000 | Maximum serialized message context sent in one completion |
| `AGENT_MAX_COST_USD` | 0.25 | Stop before another completion after reported usage reaches this amount |
| `OPENROUTER_MAX_RETRIES` | 2 | Maximum retry count for an individual provider request |
| `OPENROUTER_TIMEOUT_SECONDS` | 45 | Provider request timeout; the run deadline can stop a request sooner |

OpenRouter's reported `usage.cost` is accumulated when present. Cost reporting
is provider/model dependent, so the dollar ceiling cannot predict or prevent a
single completion from exceeding the remaining amount. Independent hard bounds
on model calls, completion tokens, tools, retries, and elapsed time still apply.
When a run hits a configured limit, Aether returns an explicit partial result
and emits `workflow.limited`; it does not claim that unfinished steps succeeded.

The stop endpoint is `POST /api/v1/agents/runs/{run_id}/stop`. It is scoped to
the authenticated owner, records `cancel_requested`, and cancels an in-flight
provider request or stops before the next tool/model operation. Cancellation
may take up to about half a second to be observed. Completed steps remain in
the run's checkpoints; cancelled runs are terminal and cannot be resumed.
Failed runs can resume from their latest worker/tool checkpoint without
restarting already completed plan steps.

## Live visibility and controls

The chat workspace receives assistant text deltas over the authenticated,
conversation-scoped WebSocket event stream. It also displays provider-reported
prompt/completion/total tokens and cost as `usage.updated` events arrive.
Unavailable cost reporting is shown as unavailable; it is not estimated.
Validated tool arguments and bounded output previews are stored in the event
trail so the owner can inspect each tool's inputs and outputs.

The process summary displays only observable routing rules, plan steps, and
completed step results. It intentionally does not expose raw model reasoning
traces. Tool inputs and outputs may include page content when browser sharing
is enabled, and are visible only to the conversation owner.

Pause requests take effect at a safe checkpoint after the active model call or
tool finishes. The saved checkpoint can be resumed. Redirecting stops the
current run, starts a new run with the new objective, and includes only the
completed step results from the previous run as context. The old run remains
in the event history as cancelled; it is not rewritten or rolled back.

## Available browser research

When local browser automation and page sharing are both explicitly enabled,
the agent can open allowlisted pages, read bounded visible text, and find a
phrase on the current page with up to five nearby snippets. The search tool is
read-only and searches only the already-open page; it does not query a search
engine, click, submit, type, or send messages. Page data is untrusted and may
be sent to OpenRouter and retained with run checkpoints. See
[Local browser automation](./LOCAL_BROWSER_AUTOMATION.md) for the opt-in and
privacy setup.

Tool actions remain individually validated and role-gated. There is no
arbitrary JavaScript, arbitrary selector, or general-purpose click tool.
Creating a task still requires its existing approval flow. Browser actions
with external side effects are not implemented.
