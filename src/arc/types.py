from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    name: str
    workspace: str
    system_prompt_files: list[str]
    model: str
    description: str = ""
    allowed_models: list[str] = field(default_factory=list)
    # acpx permission mode: "approve-all", "approve-reads", "deny-all"
    # Legacy Claude Code values ("auto", "bypassPermissions") are also accepted
    # and mapped to the nearest acpx equivalent in the dispatcher.
    permission_mode: str = "approve-all"
    local_context_files: list[str] = field(default_factory=list)
    discord: dict = field(default_factory=dict)
    timeout: int | None = None  # per-agent acpx timeout override; falls back to config.timeouts.acpx_request


@dataclass
class CronJob:
    name: str
    schedule: str
    agent: str | None = None
    prompt: str | None = None
    command: str | None = None
    description: str = ""
    model: str | None = None
    notify: str | None = None
    enabled: bool = True
    # Shell command run before the agent; non-zero exit skips agent invocation.
    pre_check: str | None = None


@dataclass
class DispatchResult:
    output: str
    model_used: str
    dispatch_type: str  # "acpx" or "ollama"


@dataclass
class IpcRequest:
    prompt: str
    agent: str | None = None
    model: str | None = None
    source: str = "cli"  # cli | discord | cron
    thread_id: str | None = None
    channel_id: str | None = None


@dataclass
class IpcResponse:
    status: str  # "ok" | "error"
    result: str | None = None
    error: str | None = None
