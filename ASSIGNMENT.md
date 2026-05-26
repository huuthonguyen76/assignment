# Capstone Project: Agent-Transparent Chat Application

## Purpose

Build a working chat application that gives users full transparency into what AI agents are doing under the hood. The app must decode and render agent execution events in real time — thinking steps, tool calls, sub-agent orchestration, parallel execution, user prompts, and artifacts.

You cannot build this without understanding how the Claude Agent SDK emits events, how to stream them to a browser, and how to decode nested agent contexts into a coherent UI.

---

## What You're Really Being Tested On

The domain is a vehicle. These are the real skills:

| Skill | Why it matters |
|-------|---------------|
| **Agent event decoding** | You must parse a stream of agent lifecycle events and map each to the correct agent context in a nested tree |
| **Real-time stream consumption** | You must consume a long-lived event stream, handle disconnects, and incrementally build state — not fetch a single JSON response |
| **Nested agent context routing** | Every event carries context about which agent emitted it. You must route events to the correct node in a tree that grows during the run |
| **Parallel execution visualization** | When the orchestrator dispatches two sub-agents concurrently, your UI must show both running simultaneously — not sequentially |
| **Interactive agent flow** | The agent can pause mid-run to ask the user a question. Your app must surface this, collect the answer, send it back, and resume |
| **Artifact collection** | Agents produce output files. Your UI must collect these from tool outputs and present them coherently |
| **State management under streaming** | Chat messages, trace trees, agent statuses, and pending questions all update simultaneously from one event stream. Your state management must handle this cleanly |

---

## Choose Your Domain

Pick one. Both exercise the same technical requirements.

---

### Domain A: "Deep Analyst" — Research Intelligence Platform

**Scenario:** The user provides a research topic — a company, a person, a stock, a market trend, a technology. A lead research agent breaks this into parallel research streams, each handled by a specialist sub-agent. The results are synthesized into a comprehensive research brief.

**Why this domain works for agent decode:**

The research pattern is the canonical multi-agent orchestration problem. Anthropic's own SDK demos use it. The lead agent decomposes a question, spawns researchers in parallel, waits for all of them, then synthesizes. This naturally exercises parallel sub-agents, sequential-after-parallel flows, artifact generation (research notes, charts, reports), and ask_user for scoping ambiguous queries.

**Agent Architecture:**

| Agent | Role | What it does |
|-------|------|-------------|
| `lead-analyst` | Orchestrator | Receives the research request. Decomposes it into 2-4 subtopics. Dispatches specialist sub-agents. Never does research directly — only coordinates and synthesizes. |
| `web-researcher` | Sub-agent (spawned per subtopic) | Searches the web for information on its assigned subtopic. Saves structured findings as markdown notes. Multiple instances run in parallel. |
| `data-analyst` | Sub-agent | Reads the research notes produced by the web researchers. Extracts key metrics, comparisons, and data points. Generates summary tables or charts. |
| `report-writer` | Sub-agent | Reads all research notes and data analysis. Produces the final research brief as a formatted document. |

**Execution flow for a typical query:**

```
User: "Research Anthropic's competitive position in the AI agent framework market"

  ◆ lead-analyst (running)
    ... thinking
    [?] ask_user: "What angle matters most — technical capabilities,
                   developer adoption, enterprise readiness, or funding?"
    ... (paused)

  [User answers: "developer adoption and enterprise readiness"]

    > web-researcher: "AI agent frameworks landscape" || parallel
    > web-researcher: "Anthropic developer adoption metrics" || parallel
    > web-researcher: "Enterprise AI agent deployments" || parallel
    > data-analyst (after researchers complete)
    > report-writer (after data-analyst completes)

  [Final: research brief with citations, comparison tables, key findings]
```

**What makes this technically interesting:**

- The orchestrator spawns **multiple instances of the same agent type** (`web-researcher`) in parallel — your trace tree must handle multiple nodes with the same agent name but different contexts
- Sequential-after-parallel: `data-analyst` cannot start until all `web-researcher` instances finish
- The `ask_user` call happens early (scoping the research), so the pause/resume flow is tested before the heavy parallel phase
- Rich artifacts at every stage: research notes (per researcher), data summaries, final report

**Existing agents and plugins you can use or adapt:**

| Resource | What it is | Link |
|----------|-----------|------|
| **Anthropic's Research Agent Demo** | Official SDK demo with exactly this pattern — lead agent, parallel researchers, data analyst, report writer. Includes hook-based tool tracking with `parent_tool_use_id`. | [anthropics/claude-agent-sdk-demos/research-agent](https://github.com/anthropics/claude-agent-sdk-demos/tree/main/research-agent) |
| **The One-Liner Research Agent** | Anthropic cookbook showing the simplest possible research agent using `query()` with `WebSearch`. Good for understanding the SDK's stateless query model before building multi-agent. | [platform.claude.com/cookbook](https://platform.claude.com/cookbook/claude-agent-sdk-00-the-one-liner-research-agent) |
| **wshobson/agents** | 112 specialized agents in 72 plugins. Includes research team agents with parallel investigation capabilities. Look at the "Agent Teams" plugin for multi-agent orchestration patterns. | [wshobson/agents](https://github.com/wshobson/agents) |
| **claude-code-hooks-multi-agent-observability** | Real-time monitoring for Claude Code agents through hook event tracking. Study this for how to trace tool calls, task handoffs, and agent lifecycle events across a multi-agent run. | [disler/claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability) |

**Seed agent prompts (if you build your own plugin):**

You can write your own agents from scratch. Here's the minimum each agent needs:

- `lead-analyst/agent.md` — System prompt instructing it to decompose research requests into 2-4 subtopics and use the `Task` tool to spawn sub-agents. Must include instructions for when to call `ask_user` (ambiguous scope, conflicting priorities, multi-industry topics).
- `web-researcher/agent.md` — System prompt for focused web research on a single subtopic. Uses `WebSearch` and `Write` to save findings as markdown notes to a known directory.
- `data-analyst/agent.md` — System prompt for reading research notes (using `Read`, `Glob`), extracting metrics, and generating structured summaries or charts (using `Bash` for chart generation).
- `report-writer/agent.md` — System prompt for synthesizing all notes and data into a final research brief. Uses `Read`, `Glob`, and `Write`.

The Anthropic research agent demo linked above provides working versions of all four. You can use them directly, adapt them, or write your own.

---

### Domain B: "PipeForge" — Data Pipeline Builder

**Scenario:** The user describes a data source and the analytics they need. An orchestrator agent builds the full data pipeline — source inspection, staging models, transformations, tests, and documentation. The output is a working set of dbt models, tests, and docs.

**Why this domain works for agent decode:**

Data pipeline construction has a natural sequential-then-parallel structure. You must inspect the source first (you can't build models without knowing the schema), then fan out into parallel work streams (model writing, test writing, doc writing can happen independently). The `ask_user` calls are genuinely useful here — data quality decisions are subjective and require human judgment. The artifacts are heavy and varied: SQL files, YAML configs, test files, markdown docs.

**Agent Architecture:**

| Agent | Role | What it does |
|-------|------|-------------|
| `pipeline-architect` | Orchestrator | Receives the data request. Dispatches source inspection first, then fans out model building, test writing, and documentation in parallel. Compiles the final DAG overview. |
| `source-inspector` | Sub-agent | Examines the raw data source. Profiles columns, infers data types, identifies nulls, duplicates, and quality issues. Writes a source profile report. |
| `model-builder` | Sub-agent | Reads the source profile. Writes dbt models — staging (1:1 with source), intermediate (business logic), and marts (final analytics tables). |
| `test-writer` | Sub-agent | Reads the source profile and models. Generates dbt schema tests (not_null, unique, accepted_values, relationships) and custom data quality assertions. |
| `doc-writer` | Sub-agent | Reads the models and source profile. Writes dbt documentation — model descriptions, column descriptions, and a DAG overview. |

**Execution flow for a typical query:**

```
User: "Build me a pipeline for our Stripe payments data.
       I need to track monthly recurring revenue by customer segment."

  ◆ pipeline-architect (running)
    ... thinking
    > source-inspector
      [T] profile_data → { columns: 23, nulls: { amount: 0.3%, currency: 0% } }
      [?] ask_user: "The `discount_amount` column is 45% null.
                     Should I: (a) default to 0, (b) exclude discounted rows,
                     or (c) create a separate model for discounted vs full-price?"
      ... (paused)

  [User answers: "Default to 0 — treat missing discount as no discount"]

      [T] write_file → source_profile.md
    > model-builder || parallel
      [T] write_file → stg_stripe__payments.sql
      [T] write_file → int_payments__monthly.sql
      [T] write_file → mart_revenue__by_segment.sql
    > test-writer || parallel
      [T] write_file → schema_tests.yml
      [T] write_file → custom_tests/test_mrr_calculation.sql
    > doc-writer || parallel
      [T] write_file → models.md

  [Final: summary of all generated files with the DAG structure]
```

**What makes this technically interesting:**

- Clear sequential-then-parallel: `source-inspector` must complete before the three parallel agents start
- The `ask_user` calls happen mid-pipeline on real data quality decisions — not just "which color do you prefer" but "how should I handle 45% null values in a financial column"
- Very artifact-heavy: each agent produces multiple files, and the trace tree must show which agent created which file
- The orchestrator's final synthesis references outputs from all sub-agents — tests the "compile after fan-in" pattern

**Existing agents and plugins you can use or adapt:**

| Resource | What it is | Link |
|----------|-----------|------|
| **dbt Labs Agent Skills** | Official dbt agent skills for Claude Code. Covers analytics engineering, unit testing, semantic layer, troubleshooting, and more. Install via Claude Code marketplace. These are skills (instruction sets), not full agents — but they provide the domain knowledge your agents need. | [dbt-labs/dbt-agent-skills](https://github.com/dbt-labs/dbt-agent-skills) |
| **dbt-model-generator skill** | Community skill specifically for generating dbt models. Good reference for what a model-builder agent should produce. | [awesomeskill.ai/skill/dbt-model-generator](https://awesomeskill.ai/skill/claude-code-plugins-plus-skills-dbt-model-generator) |
| **Anthropic's Research Agent Demo** | While it's a research domain, the orchestration pattern (lead → parallel sub-agents → synthesis) is identical to what you need. Study the architecture, adapt the domain. | [anthropics/claude-agent-sdk-demos/research-agent](https://github.com/anthropics/claude-agent-sdk-demos/tree/main/research-agent) |
| **jeremylongshore/claude-code-plugins-plus-skills** | 270+ plugins with 739 skills. Includes data engineering patterns for Airflow, Spark, Kafka, and dbt. Look for orchestration patterns you can adapt. | [jeremylongshore/claude-code-plugins-plus-skills](https://github.com/jeremylongshore/claude-code-plugins-plus-skills) |
| **Luxor Claude Marketplace** | 140 dev tools including data engineering agents. Check for dbt-adjacent agents and workflows. | [manutej/luxor-claude-marketplace](https://github.com/manutej/luxor-claude-marketplace) |

**Seed agent prompts (if you build your own plugin):**

- `pipeline-architect/agent.md` — System prompt for decomposing data pipeline requests. Must understand the dbt layer pattern (staging → intermediate → marts). Uses `Task` tool to dispatch sub-agents. Calls `ask_user` when it encounters ambiguous data modeling decisions.
- `source-inspector/agent.md` — System prompt for data profiling. Uses `Bash` to run profiling queries or scripts, `Write` to save the source profile. Must flag data quality issues and use `ask_user` for decisions that require human judgment (null handling, deduplication strategy, grain selection).
- `model-builder/agent.md` — System prompt for writing dbt SQL models. Uses `Read` to consume the source profile, `Write` to produce `.sql` files. Should follow dbt naming conventions and include appropriate `ref()` and `source()` macros.
- `test-writer/agent.md` — System prompt for generating dbt tests. Uses `Read` for source profile and model files, `Write` for schema YAML and custom test SQL.
- `doc-writer/agent.md` — System prompt for dbt documentation. Uses `Read` for all generated files, `Write` for documentation markdown and YAML descriptions.

---

## Reference Material

These resources will help you understand the SDK concepts you need. You are expected to read them.

| Resource | What you'll learn |
|----------|------------------|
| [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview) | Core concepts: sessions, tools, streaming, the agent loop |
| [Subagents in the SDK](https://platform.claude.com/docs/en/agent-sdk/subagents) | How the `Task` tool spawns sub-agents, how `parent_tool_use_id` links events to their parent |
| [Hooks in the SDK](https://platform.claude.com/docs/en/agent-sdk/hooks) | PreToolUse, PostToolUse hooks for intercepting and tracking agent behavior |
| [User Input in the SDK](https://platform.claude.com/docs/en/agent-sdk/user-input) | How `ask_user` / `AskUserQuestion` pauses the agent and resumes after user response |
| [Plugins in the SDK](https://platform.claude.com/docs/en/agent-sdk/plugins) | Plugin directory structure, how plugins are loaded, how agents are namespaced |
| [Anthropic's SDK Demos Repo](https://github.com/anthropics/claude-agent-sdk-demos) | Working examples: research agent, simple chat app, email agent. Study the research agent closely. |
| [Claude Agent SDK Python Package](https://github.com/anthropics/claude-agent-sdk-python) | The Python SDK source. Read it if you're building the backend in Python. |
| [Building Agents with the SDK (Anthropic Blog)](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk) | Anthropic's own guide to building with the SDK. Good for understanding design philosophy. |
| [Claude Code Plugins README](https://github.com/anthropics/claude-code/blob/main/plugins/README.md) | How plugins work in Claude Code — structure, installation, namespacing |
| [Create Custom Subagents (Claude Code Docs)](https://code.claude.com/docs/en/sub-agents) | How to define subagents in Claude Code plugins |
| [Awesome Claude Code](https://github.com/hesreallyhim/awesome-claude-code) | Curated list of community skills, agents, plugins, hooks. Good for finding patterns to study. |

---

## Technical Requirements (Both Domains)

### Must-Have (24 hours)

| # | Requirement |
|---|-------------|
| 1 | **Event stream consumer** — Consume the agent event stream in the browser. Handle connection, disconnection, and incremental state building. |
| 2 | **Agent event decoder** — Route each event type to the correct handler. You need to handle at minimum: session start, thinking, tool start/end, sub-agent start/end, agent response, ask_user, ask_user answered, final message, error, and done. |
| 3 | **Trace tree builder** — Build a nested tree structure from flat stream events. Events carry agent context (name, role, parent). Use this to place each event under the correct node. |
| 4 | **Expandable trace panel** — Render the trace tree with expand/collapse. Tool inputs/outputs, thinking text, and response text should be visible on expand. |
| 5 | **Parallel agent visualization** — When two or more sub-agents run concurrently, the UI must make this visually clear. |
| 6 | **ask_user flow** — When an agent asks a question, surface it in the chat, collect the user's answer, send it back to the server, and let the stream resume. |
| 7 | **Chat panel with live status** — The chat panel must never appear idle during a run. Show what's happening. |
| 8 | **Agent state indicators** — Visual distinction between queued, running, completed, and failed. |
| 9 | **Artifact collection** — Collect files produced by agents and present them in the final response. |
| 10 | **Error handling** — Show errors clearly without overwhelming the user. |

### Stretch Goals (48 hours)

| # | Requirement |
|---|-------------|
| 11 | **Stream reconnection with replay** — If the connection drops, reconnect and resume from the last received event. |
| 12 | **Auto-collapse completed nodes** — Completed sub-agent nodes collapse to a summary. |
| 13 | **Multi-run stacking** — Multiple messages in the same session each get their own trace run. Older runs collapse. |
| 14 | **Retry/Rerun on error** — Recovery actions when an agent fails. |
| 15 | **Activity ticker** — Real-time status line showing which sub-agent is active and what it's doing. |
| 16 | **Persistence** — Sessions and trace events survive page refresh. |

---

## What You're Given

**1. Agent plugin** — A Claude Code plugin with the agents pre-defined (or the seed prompts above to build your own). You are also free to use or adapt any of the open-source agents and plugins linked in the domain sections.

**2. SDK documentation** — Links provided in the Reference Material section above.

**3. Working SDK demo** — The [Anthropic research agent demo](https://github.com/anthropics/claude-agent-sdk-demos/tree/main/research-agent) is a fully working multi-agent system. Even if you pick Domain B, study this demo — the orchestration pattern is the same.

---

## Evaluation Criteria

| Area | Weight | What we're looking for |
|------|--------|----------------------|
| **Architecture** | 30% | Clean separation between stream consumption, state management, and rendering. The backend should normalize raw SDK events into a clean schema before streaming to the browser. |
| **Agent Decode Correctness** | 30% | Every event type is handled. Events route to the correct agent node. Nested sub-agent events appear under their parent. Parallel agents are distinguished from sequential. The ask_user pause/resume works end-to-end. |
| **UI/UX Quality** | 20% | The trace tree is readable and navigable. The chat never looks idle. Error states are clear. Artifacts are discoverable. |
| **Code Quality** | 20% | Typed event shapes (no untyped payloads in the decoder). Clean component structure. Tests for the decoder logic — at minimum, that each event type routes correctly and nested contexts build the right tree shape. |

---

## Deliverables

1. **Working application** — Runs locally
2. **1-pager design document** — Amazon-style (Title, Tenets, Problem, Proposed Solution, Goals, Non-goals, Open Questions). Answer the key design questions: single message or multiple? How do parallel agents appear? What happens during ask_user? How are artifacts surfaced?
3. **README** — Setup instructions, architecture overview, known limitations
4. **Decoder tests** — Unit tests proving event routing and tree construction work correctly

---


## Common Pitfalls

| Pitfall | What goes wrong |
|---------|----------------|
| **Treating the stream like a REST call** | You build the full trace tree from a single response instead of incrementally from events. The tree must grow as events arrive. |
| **Flat event list instead of a tree** | You ignore the parent agent context and render all events as siblings. Sub-agent events must nest under their parent. |
| **Losing events during ask_user** | You close the stream connection when the agent pauses for user input. The stream stays open — the server just stops emitting until the answer arrives. |
| **Race conditions on parallel agents** | Two sub-agent events arrive in the same tick and clobber each other's state. |
| **Hardcoding agent names** | Your rendering logic only works for the specific agents in the plugin. The decoder should work with any agent names — use the context dynamically. |
| **No early feedback** | The UI shows nothing until the first thinking event arrives. Show the session start immediately so the user knows something is happening. |

---

## FAQ

**Q: Can I use either domain's agents from scratch or do I have to use existing plugins?**
A: Your choice. You can use the Anthropic research agent demo directly, adapt community plugins, or write your own agents from the seed prompts. The capstone evaluates your chat application, not your agent design.

**Q: Can I mock the backend during development?**
A: Yes — a mock event stream that emits pre-recorded events is a great way to build the frontend in isolation. But the final deliverable must connect to a real agent run.

**Q: What if I pick Domain B but can't set up dbt locally?**
A: The agents can write dbt files without a running dbt installation. The pipeline builder produces files — it doesn't need to execute them. If you want the agents to actually run `dbt build`, that's a bonus, not a requirement.

**Q: Can I use Python or TypeScript for the backend?**
A: Either. The Claude Agent SDK is available in both. Pick whichever you're faster in.

**Q: What frontend framework should I use?**
A: Your call. React is the most common choice, but Vue, Svelte, or even vanilla JS with a state management library would work. The decoder logic is framework-agnostic.