# SCCS OS v0.8.1

**Smart Agent Runtime Platform for SCCS-T Product Ecosystem**

SCCS OS is a multi-agent orchestration platform that manages, monitors, and
coordinates AI agents through declarative YAML definitions, DAG-based
workflows, and an extensible plugin architecture.

```bash
pip install sccsos
sccsos init
sccsos agent list
```

---

## Quick Start

```bash
# Initialize a project
sccsos init my-project
cd my-project

# Register an agent
sccsos agent create architect

# Start an agent (background process)
sccsos agent start architect

# Ask the agent a question
sccsos agent ask architect "Design a user authentication module"

# Run a workflow
sccsos workflow validate ./workflows/my-workflow.yaml
sccsos workflow run ./workflows/my-workflow.yaml
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  CLI (click, 10 commands)    API (http.server)  │
├─────────────────────────────────────────────────┤
│              AgentRuntime (singleton)             │
├──────┬──────┬──────┬──────┬──────┬──────┬──────┤
│Agent │Agent │Work- │DAG   │Step  │Herme │Sessi-│
│Regis-│Runne │flow  │Resol │Execu │sAdap │onMgr │
│try   │r     │Engine│ver   │tor   │ter   │      │
├──────┴──────┼──────┴──────┼──────┴──────┴──────┤
│  Supervisor │  EventBus   │  Database (SQLite)  │
│  (monitor)  │  (pub/sub)  │  WAL + thread-safe  │
├─────────────┴─────────────┴────────────────────┤
│  PolicyEngine + CommandWhitelist  (security)    │
├─────────────────────────────────────────────────┤
│  Tracer + Auditor + Webhook + Alert  (observability) │
└─────────────────────────────────────────────────┘
```

### Core Modules

| Module | LOC | Description |
|--------|-----|-------------|
| `core/` | ~4,200 | Engine: runtime, runner, orchestrator, DAG resolver |
| `cli/` | ~2,000 | CLI: agent, workflow, system, config subcommands |
| `observability/` | ~1,000 | Tracing, auditing, pricing, webhooks, alerts |
| `memory/` | ~650 | KV store, knowledge base, vector search |
| `security/` | ~410 | Policy enforcement, command whitelist |
| `api/` | ~530 | HTTP REST API server |

### Key Features

- **Multi-agent orchestration**: DAG-based workflows with parallel execution
- **Declarative agents**: YAML-defined agent specs with lifecycle management
- **Background processes**: Agents run as supervised daemon threads
- **Event-driven**: EventBus decouples workflow engine from observers
- **Observability**: Distributed tracing, cost tracking, webhook alerts
- **Security**: Budget limits, tool whitelist, command sandbox
- **Schema migration**: Versioned workflow defs with auto-migration
- **Config hot-reload**: `sccsos config reload` applies changes without restart

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `sccsos init` | Initialize a new project |
| `sccsos agent list/start/stop/pause/resume/restart` | Agent lifecycle |
| `sccsos agent ask <name> <prompt>` | Send prompt to running agent |
| `sccsos workflow validate/run/status/cancel/list/visualize` | Workflow management |
| `sccsos trace list/show` | View distributed traces |
| `sccsos audit report/log` | Cost and usage reports |
| `sccsos memory save/get/list/delete/clear` | Persistent KV store |
| `sccsos session list/show/close` | Conversation history |
| `sccsos config reload` | Hot-reload configuration |
| `sccsos health` | System health check |

---

## Workflow Example

```yaml
name: architecture-review
schema_version: '1.1'
steps:
  - id: requirements
    agent: architect
    prompt: >
      Given the following requirements, create a detailed
      architecture design:
      {{ steps.input.context }}

  - id: review
    agent: reviewer
    prompt: >
      Review the architecture:
      {{ steps.requirements.response }}
    depends_on:
      - requirements
```

### Template Filters

| Filter | Usage |
|--------|-------|
| `json_parse` | `{{ steps.api.response \| json_parse }}` |
| `json_dumps` | `{{ data \| json_dumps(2) }}` |
| `pick` | `{{ steps.result \| pick('data', default=[]) }}` |
| `strptime` / `strftime` | `{{ date \| strptime \| strftime('%Y-%m-%d') }}` |
| `truncate_cn` | `{{ text \| truncate_cn(80) }}` (CJK-aware) |

---

## Development

```bash
git clone https://github.com/your-org/sccsos
cd sccsos
pip install -e ".[dev]"
python -m pytest tests/
```

### Tests

- **246 tests**, all passing
- 9 test files covering all modules
- MockHermesAdapter for hermetic workflow testing

### Build

```bash
python -m build
```

---

## License

MIT
