---
id: model-routing
title: Model Routing
sidebar_position: 4
---

# Model Routing

arc routes prompts to two backends: Claude (via `acpx`) and Ollama (via `httpx`). The backend is selected automatically based on the model string prefix.

## Two dispatch paths

### Claude via acpx

Any model string starting with `claude-` is dispatched via `acpx`, the Claude Code session manager. `acpx` manages the Claude Code CLI process, handles authentication, and exposes a session API.

The dispatcher calls:

```bash
acpx --format quiet \
  --cwd <workspace> \
  --model <model> \
  --approve-all \
  --system-prompt "<concatenated system prompt>" \
  claude exec \
  --file <tmpfile>
```

`--format quiet` suppresses `acpx`'s progress output. The prompt is written to a temp file to avoid shell quoting issues with multi-line prompts.

### Ollama via httpx

Any model string starting with `ollama/` is dispatched via `httpx` to an Ollama-compatible REST API. arc calls the `/v1/chat/completions` endpoint directly (no Ollama client library).

## Model prefix convention

| Prefix | Backend | Example |
|---|---|---|
| `claude-` | acpx / Claude Code | `claude-sonnet-4-6` |
| `ollama/` | httpx / Ollama API | `ollama/qwen3:8b` |
| `ollama/<endpoint>/` | httpx / named Ollama endpoint | `ollama/remote/qwen3:32b` |

Any other prefix raises a `DispatchError`: `Unknown model type: 'gpt-4'. Expected 'claude-*' or 'ollama/*'.`

## Model resolution priority

When a prompt arrives, the effective model is resolved in this order:

1. **`--model` CLI flag** (or `model` field in the IPC request)
2. **`/model` Discord command** (sticky per channel, stored in daemon memory)
3. **Agent config `model` field** (the default)

The first non-null value wins. If the result is in `allowed_models` (or `allowed_models` is empty), dispatch proceeds. Otherwise, a `DispatchError` is returned.

## allowed_models gatekeeping

`allowed_models` is a list of permitted models on an agent. If the list is empty, any model with a valid prefix is accepted.

```yaml
allowed_models:
  - claude-sonnet-4-6
  - claude-haiku-4-5
```

With this config, requests for `ollama/qwen3:8b` or `claude-opus-4-7` will be rejected:

```
Error: Model 'claude-opus-4-7' is not allowed for agent 'coach'.
Allowed: claude-sonnet-4-6, claude-haiku-4-5
```

This is enforced in the dispatcher before any backend call is made.

## Ollama endpoint configuration

Ollama endpoints are named in `config.yaml`:

```yaml
ollama:
  endpoints:
    local:
      url: http://localhost:11434/v1
    remote:
      url: http://192.168.1.100:11434/v1
    kyle:
      url: http://kyle-nuc.tailnet:11434/v1
```

The `local` endpoint is the default for `ollama/<model>` strings. Named endpoints are accessed with `ollama/<endpoint>/<model>`.

## Using named endpoints

```bash
# Local Ollama (uses the 'local' endpoint)
arc ask --agent coach --model ollama/qwen3:8b "Hello"

# Named endpoint (kyle-nuc on Tailscale)
arc ask --agent coach --model ollama/kyle/qwen3:32b "Hello"
```

In an agent YAML:

```yaml
model: ollama/remote/llama3.2:latest
allowed_models:
  - ollama/local/qwen3:8b
  - ollama/remote/llama3.2:latest
```

The endpoint name after `ollama/` is looked up in `config.ollama.endpoints`. An unknown endpoint name raises: `Unknown Ollama endpoint 'nonexistent'. Configured: local, remote, kyle`

## Per-cron-job model override

Individual cron jobs can override the agent's model:

```yaml
jobs:
  heartbeat:
    schedule: "*/30 * * * *"
    agent: coach
    model: claude-haiku-4-5   # cheaper for frequent runs
    prompt: "Read HEARTBEAT.md and follow it."
```

The model override follows the same `allowed_models` validation as any other override.

## Routing the same agent through different models

You can run the same agent with different models in different contexts:

```bash
# Use Sonnet for complex analysis
arc ask --agent coach --model claude-sonnet-4-6 \
  "Review my last month of training and identify patterns."

# Use Haiku for quick questions
arc ask --agent coach --model claude-haiku-4-5 \
  "What's today's workout?"

# Use a local Ollama model (free, private)
arc ask --agent coach --model ollama/qwen3:8b \
  "Summarize today's metrics."
```

In cron jobs, use cheaper models for frequent tasks and more capable models for complex weekly or monthly tasks.

## Local context files for Ollama

Ollama agents cannot read the filesystem via tools. Use `local_context_files` to inject file contents into the request:

```yaml
name: trainer
workspace: /workspace/fitness-coach
model: ollama/qwen3:8b
local_context_files:
  - programs/current.md
  - weeks/current.md
```

The files are injected as a system message before the user prompt. This gives the Ollama model the necessary context without needing filesystem access.

## Error handling

| Error | Cause | Resolution |
|---|---|---|
| `Unknown model type` | Model prefix is not `claude-` or `ollama/` | Check the model string |
| `Model 'X' is not allowed` | Model not in `allowed_models` | Add to `allowed_models` or remove the list |
| `Unknown Ollama endpoint` | Endpoint name not in `config.ollama.endpoints` | Add the endpoint to config |
| `Cannot connect to Ollama` | Ollama not running or wrong URL | Start Ollama or fix `url` in config |
| `acpx timed out` | acpx took longer than `timeouts.acpx_request` | Increase the timeout or check acpx |
| `Ollama timed out` | Ollama took longer than `timeouts.ollama_request` | Increase the timeout or check Ollama |
