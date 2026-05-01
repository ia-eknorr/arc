import asyncio
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from arc.config import load_config
from arc.dispatcher import DispatchError, dispatch
from arc.types import AgentConfig
from arc.utils import configure_logging, is_process_running, read_pid, write_pid

app = typer.Typer(
    name="arc",
    help="Agent Router CLI -- lightweight agent dispatch and scheduling.",
    no_args_is_help=True,
)

daemon_app = typer.Typer(name="daemon", help="Manage the arc daemon.", no_args_is_help=True)
app.add_typer(daemon_app, name="daemon")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_agent_or_none(agent_name: str | None, config_dir: Path | None) -> AgentConfig | None:
    if not agent_name:
        return None
    from arc.agents import load_agent

    try:
        return load_agent(agent_name, config_dir)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


def _read_prompt(prompt_arg: str | None, stdin_data: str | None) -> str:
    parts = []
    if stdin_data and not sys.stdin.isatty():
        parts.append(stdin_data.strip())
    if prompt_arg:
        parts.append(prompt_arg.strip())
    if not parts:
        typer.echo("Error: provide a prompt argument or pipe text via stdin.", err=True)
        raise typer.Exit(1)
    return "\n\n".join(parts)


def _daemon_is_running(config_dir: Path | None = None) -> bool:
    cfg = load_config(config_dir)
    pid = read_pid(cfg.daemon.pid_file)
    return pid is not None and is_process_running(pid)


def _arc_executable() -> str:
    return shutil.which("arc") or sys.argv[0]


def _logs_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return Path(config_dir) / "logs"
    cfg = load_config(None)
    return Path(cfg.daemon.socket_path).expanduser().parent / "logs"


# ---------------------------------------------------------------------------
# arc ask
# ---------------------------------------------------------------------------


@app.command()
def ask(
    prompt: Annotated[str | None, typer.Argument(help="Prompt to send.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", "-a", help="Agent name.")] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Override model (e.g. claude-haiku-4-5, ollama/qwen3:8b)."),
    ] = None,
    pretty: Annotated[bool, typer.Option("--pretty", help="Show dispatch info header.")] = False,
    config_dir: Annotated[
        Path | None,
        typer.Option("--config-dir", hidden=True, help="Override config directory."),
    ] = None,
) -> None:
    """Send a prompt to an agent and print the response."""
    stdin_data = None
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()

    full_prompt = _read_prompt(prompt, stdin_data)

    cfg = load_config(config_dir)
    configure_logging(cfg.daemon.log_level)

    resolved_agent = _load_agent_or_none(agent, config_dir)

    if not resolved_agent and not model:
        typer.echo("Error: provide --agent or --model (or both).", err=True)
        raise typer.Exit(1)

    if not resolved_agent:
        resolved_agent = AgentConfig(
            name="_inline",
            workspace=str(Path.cwd()),
            system_prompt_files=[],
            model=model or "claude-sonnet-4-6",
            allowed_models=[model] if model else [],
        )

    async def _run() -> None:
        from arc import ipc as _ipc

        # Try daemon first (it holds model overrides and logging).
        response = await _ipc.request(
            cfg,
            {
                "prompt": full_prompt,
                "agent": resolved_agent.name,
                "model": model,
                "source": "cli",
            },
        )

        if response is not None:
            if response["status"] == "error":
                typer.echo(f"Error: {response['error']}", err=True)
                raise typer.Exit(1)
            if pretty:
                typer.echo("\n[daemon]\n")
            typer.echo(response["result"])
            return

        # Daemon not running -- auto-start if configured, then retry once.
        if cfg.daemon.auto_start and not _daemon_is_running(config_dir):
            _start_daemon_background()
            await asyncio.sleep(1.0)
            response = await _ipc.request(cfg, {
                "prompt": full_prompt,
                "agent": resolved_agent.name,
                "model": model,
                "source": "cli",
            })
            if response is not None:
                if response["status"] == "error":
                    typer.echo(f"Error: {response['error']}", err=True)
                    raise typer.Exit(1)
                if pretty:
                    typer.echo("\n[daemon]\n")
                typer.echo(response["result"])
                return

        # Fall back to direct dispatch.
        try:
            result = await dispatch(
                prompt=full_prompt,
                agent=resolved_agent,
                model_override=model,
                one_shot=True,
                config=cfg,
            )
        except DispatchError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e

        if pretty:
            typer.echo(f"\n[{result.dispatch_type} / {result.model_used}]\n")
        typer.echo(result.output)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# arc daemon
# ---------------------------------------------------------------------------


def _start_daemon_background() -> None:
    """Spawn the daemon as a detached background process."""
    subprocess.Popen(
        [_arc_executable(), "daemon", "start", "--foreground"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@daemon_app.command("start")
def daemon_start(
    foreground: Annotated[
        bool, typer.Option("--foreground", help="Run in foreground (for systemd).")
    ] = False,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Start the arc daemon."""
    cfg = load_config(config_dir)

    if _daemon_is_running(config_dir):
        typer.echo("Daemon is already running.")
        raise typer.Exit(0)

    if foreground:
        from arc.daemon import run_daemon
        run_daemon()
    else:
        _start_daemon_background()
        typer.echo("Daemon started.")


@daemon_app.command("stop")
def daemon_stop(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Stop the arc daemon."""
    cfg = load_config(config_dir)
    pid = read_pid(cfg.daemon.pid_file)

    if pid is None or not is_process_running(pid):
        typer.echo("Daemon is not running.")
        raise typer.Exit(0)

    try:
        import os
        os.kill(pid, signal.SIGTERM)
        typer.echo(f"Daemon stopped (pid={pid}).")
    except ProcessLookupError:
        typer.echo("Daemon process not found.")


@daemon_app.command("status")
def daemon_status(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Show daemon status."""
    cfg = load_config(config_dir)
    pid = read_pid(cfg.daemon.pid_file)
    socket_path = Path(cfg.daemon.socket_path).expanduser()

    if pid and is_process_running(pid):
        typer.echo(f"Daemon running (pid={pid}, socket={socket_path})")
    else:
        typer.echo("Daemon not running.")
        raise typer.Exit(1)


@daemon_app.command("restart")
def daemon_restart(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Restart the arc daemon."""
    cfg = load_config(config_dir)
    pid = read_pid(cfg.daemon.pid_file)

    if pid and is_process_running(pid):
        import os
        os.kill(pid, signal.SIGTERM)
        import time
        time.sleep(0.5)

    _start_daemon_background()
    typer.echo("Daemon restarted.")


@daemon_app.command("install")
def daemon_install(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Generate a systemd user service unit file."""
    arc_bin = _arc_executable()
    unit = f"""\
[Unit]
Description=arc agent router daemon
After=network.target

[Service]
Type=simple
ExecStart={arc_bin} daemon start --foreground
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    unit_dir = Path("~/.config/systemd/user").expanduser()
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file = unit_dir / "arc-daemon.service"
    unit_file.write_text(unit)
    typer.echo(f"Wrote {unit_file}")
    typer.echo("To enable: systemctl --user enable --now arc-daemon")


# ---------------------------------------------------------------------------
# arc cron
# ---------------------------------------------------------------------------


cron_app = typer.Typer(name="cron", help="Manage scheduled cron jobs.", no_args_is_help=True)
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """List all configured cron jobs."""
    from arc.cron import load_jobs
    cfg = load_config(config_dir)
    jobs = load_jobs(cfg)
    if not jobs:
        typer.echo("No cron jobs configured. Add them to ~/.arc/cron/jobs.yaml")
        return
    for job in jobs:
        status = "enabled" if job.enabled else "disabled"
        model = f"  model={job.model}" if job.model else ""
        notify = f"  notify={job.notify}" if job.notify else ""
        typer.echo(f"{job.name:<20} [{status}]  {job.schedule}{model}{notify}")
        if job.description:
            typer.echo(f"  {job.description}")


@cron_app.command("run")
def cron_run(
    name: Annotated[str, typer.Argument(help="Job name to run immediately.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Run a cron job immediately."""
    from arc.cron import load_jobs
    cfg = load_config(config_dir)
    jobs = {j.name: j for j in load_jobs(cfg)}
    if name not in jobs:
        typer.echo(f"Error: job '{name}' not found.", err=True)
        raise typer.Exit(1)
    job = jobs[name]

    async def _run() -> None:
        from arc import ipc as _ipc
        # Route through daemon's run_cron_job so Discord notify and logging fire.
        response = await _ipc.request(cfg, {"op": "cron_run", "job": name})
        if response is None:
            # Daemon not running - dispatch directly (no Discord notify in this path).
            from arc.agents import load_agent
            from arc.dispatcher import DispatchError, dispatch
            try:
                agent = load_agent(job.agent, config_dir)
                result = await dispatch(
                    prompt=job.prompt,
                    agent=agent,
                    model_override=job.model,
                    one_shot=True,
                    config=cfg,
                )
                typer.echo(result.output)
            except (FileNotFoundError, DispatchError) as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1) from e
        elif response["status"] == "error":
            typer.echo(f"Error: {response['error']}", err=True)
            raise typer.Exit(1)
        else:
            typer.echo(response["result"])

    asyncio.run(_run())


@cron_app.command("next")
def cron_next(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Show next scheduled run time for each enabled job."""
    from arc.cron import load_jobs
    from apscheduler.triggers.cron import CronTrigger
    from datetime import datetime, timezone

    cfg = load_config(config_dir)
    jobs = load_jobs(cfg)
    if not jobs:
        typer.echo("No cron jobs configured.")
        return
    now = datetime.now(timezone.utc)
    for job in jobs:
        if not job.enabled:
            typer.echo(f"{job.name:<20} [disabled]")
            continue
        trigger = CronTrigger.from_crontab(job.schedule)
        next_run = trigger.get_next_fire_time(None, now)
        typer.echo(f"{job.name:<20} {next_run.astimezone().strftime('%Y-%m-%d %H:%M %Z') if next_run else 'unknown'}")


@cron_app.command("enable")
def cron_enable(
    name: Annotated[str, typer.Argument(help="Job name to enable.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Enable a cron job."""
    from arc.cron import set_job_enabled
    cfg = load_config(config_dir)
    if not set_job_enabled(cfg, name, True):
        typer.echo(f"Error: job '{name}' not found.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Enabled {name}. Restart the daemon to apply.")


@cron_app.command("disable")
def cron_disable(
    name: Annotated[str, typer.Argument(help="Job name to disable.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Disable a cron job."""
    from arc.cron import set_job_enabled
    cfg = load_config(config_dir)
    if not set_job_enabled(cfg, name, False):
        typer.echo(f"Error: job '{name}' not found.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Disabled {name}. Restart the daemon to apply.")


# ---------------------------------------------------------------------------
# arc status
# ---------------------------------------------------------------------------


def _relative_time(iso: str) -> str:
    """Format an ISO timestamp as a human-readable relative string."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    then = datetime.fromisoformat(iso)
    delta = int((then - now).total_seconds())
    if delta < 60:
        return "in <1 min"
    if delta < 3600:
        return f"in {delta // 60} min"
    if delta < 86400:
        h, m = divmod(delta // 60, 60)
        return f"in {h}h {m}m"
    return then.strftime("%a %Y-%m-%d %H:%M")


def _next_fire_offline(schedule: str) -> str | None:
    """Compute next fire time for a cron expression without a running scheduler."""
    from datetime import datetime, timezone
    from apscheduler.triggers.cron import CronTrigger
    try:
        trigger = CronTrigger.from_crontab(schedule)
        nrt = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        return nrt.isoformat() if nrt else None
    except Exception:
        return None


def _print_status(data: dict, daemon_running: bool) -> None:
    """Format and print arc status output."""
    if daemon_running:
        d = data["daemon"]
        typer.echo(f"daemon    running (pid={d['pid']}, socket={d['socket']})")
    else:
        typer.echo("daemon    not running")

    agents = data.get("agents", [])
    if agents:
        typer.echo("\nagents")
        col_name = max(len(a["name"]) for a in agents)
        col_model = max(len(a["model"]) for a in agents)
        for a in agents:
            discord = f"  discord {a['discord_channel']}" if a.get("discord_channel") else ""
            typer.echo(
                f"  {a['name']:<{col_name}}  {a['model']:<{col_model}}  {a['workspace']}{discord}"
            )
    else:
        typer.echo("\nagents    (none configured)")

    cron = data.get("cron", [])
    if cron:
        typer.echo("\ncron")
        col_name = max(len(j["name"]) for j in cron)
        for j in cron:
            if not j["enabled"]:
                next_str = "disabled"
            elif j.get("next_run"):
                next_str = f"next: {_relative_time(j['next_run'])}"
            else:
                next_str = "next: unknown"
            typer.echo(f"  {j['name']:<{col_name}}  {next_str}")


@app.command("status")
def status_cmd(
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", hidden=True)
    ] = None,
) -> None:
    """Show daemon state, configured agents, and scheduled cron jobs."""
    from arc.agents import list_agents
    from arc.cron import load_jobs

    async def _run() -> None:
        from arc import ipc as _ipc
        cfg = load_config(config_dir)
        response = await _ipc.request(cfg, {"op": "status", "source": "cli"})
        if response and response.get("status") == "ok":
            _print_status(response, daemon_running=True)
            return

        # Daemon not running: build status from config files directly.
        agents = [
            {
                "name": a.name,
                "model": a.model,
                "workspace": a.workspace,
                "discord_channel": a.discord.get("channel_id"),
            }
            for a in list_agents(config_dir)
        ]
        cron = [
            {
                "name": j.name,
                "schedule": j.schedule,
                "enabled": j.enabled,
                "next_run": _next_fire_offline(j.schedule) if j.enabled else None,
            }
            for j in load_jobs(cfg)
        ]
        _print_status({"agents": agents, "cron": cron}, daemon_running=False)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# arc tokens
# ---------------------------------------------------------------------------


def _codeburn_bin() -> list[str]:
    """Return the codeburn command prefix, preferring a global install over npx."""
    cb = shutil.which("codeburn")
    if cb:
        return [cb]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "codeburn"]
    return []


@app.command("tokens")
def tokens_cmd(
    agent: Annotated[
        str | None,
        typer.Option("--agent", "-a", help="Scope to a single agent's workspace."),
    ] = None,
    period: Annotated[
        str,
        typer.Option("--period", "-p", help="Period: today, week, month, all."),
    ] = "today",
    subcommand: Annotated[
        str,
        typer.Option("--cmd", help="codeburn subcommand: status, report, today, month."),
    ] = "status",
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", hidden=True)
    ] = None,
) -> None:
    """Show token usage per agent via codeburn."""
    cb = _codeburn_bin()
    if not cb:
        typer.echo(
            "Error: codeburn not found. Install with: npm install -g codeburn",
            err=True,
        )
        raise typer.Exit(1)

    from arc.agents import list_agents, load_agent

    cmd = cb + [subcommand, "--provider", "claude"]

    if agent:
        try:
            agent_cfg = load_agent(agent, config_dir)
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e
        project_name = Path(agent_cfg.workspace).name
        cmd += ["--project", project_name]
        typer.echo(f"[agent: {agent_cfg.name}  workspace: {agent_cfg.workspace}]\n")
    else:
        agents = list_agents(config_dir)
        if agents:
            col = max(len(a.name) for a in agents)
            typer.echo("Configured agents:")
            for a in agents:
                typer.echo(f"  {a.name:<{col}}  {a.workspace}")
                cmd += ["--project", Path(a.workspace).name]
            typer.echo()

    if subcommand == "status":
        cmd += ["--period", period]

    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


# ---------------------------------------------------------------------------
# arc setup
# ---------------------------------------------------------------------------


@app.command("setup")
def setup_cmd(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Interactive first-run setup wizard."""
    from arc.setup_wizard import (
        check_all_deps,
        create_arc_dirs,
        create_default_config,
        create_default_env,
        write_discord_config,
    )

    arc_dir = (config_dir or Path("~/.arc")).expanduser()
    typer.echo(f"arc setup -- configuring {arc_dir}\n")

    # Check deps
    deps = check_all_deps()
    for name, path in deps.items():
        status = path or "NOT FOUND"
        marker = "ok" if path else "MISSING"
        typer.echo(f"  [{marker}] {name}: {status}")

    if not deps["acpx"]:
        typer.echo("\nInstall acpx: npm install -g acpx@latest", err=True)
    if not deps["claude"]:
        typer.echo("Install Claude Code: curl -fsSL https://claude.ai/install.sh | bash", err=True)

    typer.echo()

    # Create dirs and default config
    create_arc_dirs(arc_dir)
    if create_default_config(arc_dir):
        typer.echo(f"Created {arc_dir}/config.yaml")
    else:
        typer.echo(f"Config already exists: {arc_dir}/config.yaml")

    if create_default_env(arc_dir):
        typer.echo(f"Created {arc_dir}/.env (chmod 600)")

    # Discord setup
    typer.echo()
    setup_discord = typer.confirm("Set up Discord bot?", default=False)
    if setup_discord:
        token = typer.prompt("Discord bot token")
        guild_id = typer.prompt("Discord guild ID")
        write_discord_config(arc_dir, token, guild_id)
        typer.echo("Discord configured. Restart daemon to apply.")

    typer.echo("\nSetup complete. Run: arc daemon start")


# ---------------------------------------------------------------------------
# arc import-openclaw
# ---------------------------------------------------------------------------


@app.command("import-openclaw")
def import_openclaw_cmd(
    from_dir: Annotated[
        Path, typer.Option("--from", help="OpenClaw config directory.")
    ] = Path("~/.openclaw"),
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without writing.")] = False,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Import agents and cron jobs from an OpenClaw installation."""
    from arc.import_openclaw import import_from_path

    openclaw_dir = from_dir.expanduser()
    arc_dir = (config_dir or Path("~/.arc")).expanduser()

    if not openclaw_dir.exists():
        typer.echo(f"Error: OpenClaw directory not found: {openclaw_dir}", err=True)
        raise typer.Exit(1)

    if dry_run:
        typer.echo(f"Dry run -- reading from {openclaw_dir}, would write to {arc_dir}\n")
    else:
        typer.echo(f"Importing from {openclaw_dir} into {arc_dir}\n")

    summary = import_from_path(openclaw_dir, arc_dir, dry_run=dry_run)

    if summary["errors"]:
        for e in summary["errors"]:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    for name in summary["agents_imported"]:
        prefix = "[dry-run] would import" if dry_run else "Imported"
        typer.echo(f"  {prefix} agent: {name}")

    for name in summary["jobs_imported"]:
        prefix = "[dry-run] would import" if dry_run else "Imported"
        typer.echo(f"  {prefix} cron job: {name}")

    for msg in summary["skipped"]:
        typer.echo(f"  Skipped: {msg}")

    if not summary["agents_imported"] and not summary["jobs_imported"] and not summary["skipped"]:
        typer.echo("Nothing to import.")
    elif not dry_run:
        typer.echo("\nDone. Review ~/.arc/agents/ and restart the daemon.")


# ---------------------------------------------------------------------------
# arc cron add/remove/edit/history
# ---------------------------------------------------------------------------


@cron_app.command("add")
def cron_add(
    name: Annotated[str, typer.Option("--name", "-n", help="Job name.")] = "",
    schedule: Annotated[str, typer.Option("--schedule", "-s", help="Cron schedule expression.")] = "",
    agent: Annotated[str, typer.Option("--agent", "-a", help="Agent name.")] = "",
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="Prompt to send.")] = "",
    notify: Annotated[str, typer.Option("--notify", help="Notification mode: discord, discord_on_urgent.")] = "",
    model: Annotated[str | None, typer.Option("--model", "-m", help="Model override.")] = None,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Add a new cron job."""
    name = name or typer.prompt("Job name")
    schedule = schedule or typer.prompt("Schedule (cron expression)")
    agent = agent or typer.prompt("Agent name")
    prompt = prompt or typer.prompt("Prompt")

    cfg = load_config(config_dir)
    config_dir_path = Path(cfg.daemon.pid_file).expanduser().parent
    jobs_file = config_dir_path / "cron" / "jobs.yaml"
    jobs_file.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if jobs_file.exists():
        import yaml
        data = yaml.safe_load(jobs_file.read_text()) or {}
    data.setdefault("jobs", {})

    if name in data["jobs"]:
        typer.echo(f"Error: job '{name}' already exists. Use 'arc cron edit' to modify.", err=True)
        raise typer.Exit(1)

    job: dict = {"schedule": schedule, "agent": agent, "prompt": prompt, "enabled": True}
    if notify:
        job["notify"] = notify
    if model:
        job["model"] = model

    data["jobs"][name] = job
    import yaml
    jobs_file.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    typer.echo(f"Added job '{name}'. Restart daemon to schedule it.")


@cron_app.command("remove")
def cron_remove(
    name: Annotated[str, typer.Argument(help="Job name to remove.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Remove a cron job."""
    import yaml
    cfg = load_config(config_dir)
    config_dir_path = Path(cfg.daemon.pid_file).expanduser().parent
    jobs_file = config_dir_path / "cron" / "jobs.yaml"

    if not jobs_file.exists():
        typer.echo(f"Error: job '{name}' not found.", err=True)
        raise typer.Exit(1)

    data = yaml.safe_load(jobs_file.read_text()) or {}
    if name not in (data.get("jobs") or {}):
        typer.echo(f"Error: job '{name}' not found.", err=True)
        raise typer.Exit(1)

    del data["jobs"][name]
    jobs_file.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    typer.echo(f"Removed job '{name}'. Restart daemon to apply.")


@cron_app.command("edit")
def cron_edit(
    name: Annotated[str, typer.Argument(help="Job name to edit.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Open the cron jobs file in $EDITOR."""
    import os
    cfg = load_config(config_dir)
    config_dir_path = Path(cfg.daemon.pid_file).expanduser().parent
    jobs_file = config_dir_path / "cron" / "jobs.yaml"
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(jobs_file)])


@cron_app.command("history")
def cron_history(
    name: Annotated[str | None, typer.Argument(help="Filter by job name.")] = None,
    last: Annotated[int, typer.Option("--last", "-n", help="Number of entries to show.")] = 10,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Show recent cron job run history."""
    import json
    log_file = _logs_dir(config_dir) / "cron.jsonl"

    if not log_file.exists():
        typer.echo("No cron history yet.")
        return

    lines = log_file.read_text().splitlines()
    records = []
    for line in lines:
        try:
            r = json.loads(line)
            if name is None or r.get("job") == name:
                records.append(r)
        except json.JSONDecodeError:
            pass

    for r in records[-last:]:
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        job = r.get("job", "?")
        status = r.get("status", "?")
        preview = r.get("output_preview", "")[:80]
        typer.echo(f"{ts}  {job:<20} [{status}]  {preview}")


# ---------------------------------------------------------------------------
# arc agent
# ---------------------------------------------------------------------------


agent_app = typer.Typer(name="agent", help="Manage arc agents.", no_args_is_help=True)
app.add_typer(agent_app, name="agent")


def _agents_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return Path(config_dir) / "agents"
    cfg = load_config(None)
    return Path(cfg.daemon.pid_file).expanduser().parent / "agents"


@agent_app.command("list")
def agent_list(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """List configured agents."""
    from arc.agents import list_agents
    agents = list_agents(config_dir)
    if not agents:
        typer.echo("No agents configured. Add YAML files to ~/.arc/agents/")
        return
    for a in agents:
        channel = a.discord.get("channel_id", "")
        channel_str = f"  channel={channel}" if channel else ""
        typer.echo(f"{a.name:<16} {a.model:<28} {a.workspace}{channel_str}")


@agent_app.command("show")
def agent_show(
    name: Annotated[str, typer.Argument(help="Agent name.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Show agent configuration."""
    agents_dir = _agents_dir(config_dir)
    path = agents_dir / f"{name}.yaml"
    if not path.exists():
        typer.echo(f"Error: agent '{name}' not found.", err=True)
        raise typer.Exit(1)
    typer.echo(path.read_text())


@agent_app.command("create")
def agent_create(
    from_file: Annotated[Path | None, typer.Option("--from", help="Copy from existing YAML file.")] = None,
    name: Annotated[str, typer.Option("--name", "-n")] = "",
    workspace: Annotated[str, typer.Option("--workspace", "-w")] = "",
    model: Annotated[str, typer.Option("--model", "-m")] = "",
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Create a new agent."""
    import yaml
    agents_dir = _agents_dir(config_dir)
    agents_dir.mkdir(parents=True, exist_ok=True)

    if from_file:
        if not from_file.exists():
            typer.echo(f"Error: file not found: {from_file}", err=True)
            raise typer.Exit(1)
        data = yaml.safe_load(from_file.read_text())
        dest_name = name or data.get("name") or from_file.stem
        dest = agents_dir / f"{dest_name}.yaml"
        if dest.exists():
            typer.echo(f"Error: agent '{dest_name}' already exists.", err=True)
            raise typer.Exit(1)
        data["name"] = dest_name
        dest.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
        typer.echo(f"Created agent '{dest_name}'.")
        return

    name = name or typer.prompt("Agent name")
    workspace = workspace or typer.prompt("Workspace path")
    model = model or typer.prompt("Model", default="claude-sonnet-4-6")

    dest = agents_dir / f"{name}.yaml"
    if dest.exists():
        typer.echo(f"Error: agent '{name}' already exists.", err=True)
        raise typer.Exit(1)

    data = {
        "name": name,
        "description": "",
        "workspace": workspace,
        "system_prompt_files": ["AGENTS.md", "IDENTITY.md", "SOUL.md", "USER.md", "TOOLS.md"],
        "model": model,
        "allowed_models": [model],
        "permission_mode": "approve-all",
        "discord": {},
    }
    dest.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    typer.echo(f"Created agent '{name}' at {dest}")


@agent_app.command("edit")
def agent_edit(
    name: Annotated[str, typer.Argument(help="Agent name.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Open an agent config in $EDITOR."""
    import os
    agents_dir = _agents_dir(config_dir)
    path = agents_dir / f"{name}.yaml"
    if not path.exists():
        typer.echo(f"Error: agent '{name}' not found.", err=True)
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(path)])


@agent_app.command("delete")
def agent_delete(
    name: Annotated[str, typer.Argument(help="Agent name.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Delete an agent."""
    agents_dir = _agents_dir(config_dir)
    path = agents_dir / f"{name}.yaml"
    if not path.exists():
        typer.echo(f"Error: agent '{name}' not found.", err=True)
        raise typer.Exit(1)
    if not yes:
        typer.confirm(f"Delete agent '{name}'?", abort=True)
    path.unlink()
    typer.echo(f"Deleted agent '{name}'.")


@agent_app.command("clone")
def agent_clone(
    name: Annotated[str, typer.Argument(help="Source agent name.")],
    new_name: Annotated[str, typer.Argument(help="New agent name.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Clone an agent under a new name."""
    import yaml
    agents_dir = _agents_dir(config_dir)
    src = agents_dir / f"{name}.yaml"
    dest = agents_dir / f"{new_name}.yaml"
    if not src.exists():
        typer.echo(f"Error: agent '{name}' not found.", err=True)
        raise typer.Exit(1)
    if dest.exists():
        typer.echo(f"Error: agent '{new_name}' already exists.", err=True)
        raise typer.Exit(1)
    data = yaml.safe_load(src.read_text())
    data["name"] = new_name
    data.setdefault("discord", {}).pop("channel_id", None)
    dest.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    typer.echo(f"Cloned '{name}' -> '{new_name}'. Edit {dest} to configure.")


# ---------------------------------------------------------------------------
# arc log
# ---------------------------------------------------------------------------


log_app = typer.Typer(name="log", help="View arc logs.", no_args_is_help=True)
app.add_typer(log_app, name="log")


def _read_jsonl(path: Path, last: int, job_filter: str | None = None) -> list[dict]:
    import json
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
            if job_filter is None or r.get("job") == job_filter or r.get("agent") == job_filter:
                records.append(r)
        except json.JSONDecodeError:
            pass
    return records[-last:]


@log_app.command("routing")
def log_routing(
    last: Annotated[int, typer.Option("--last", "-n")] = 20,
    agent: Annotated[str | None, typer.Option("--agent", "-a")] = None,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Show recent routing log entries."""
    log_file = _logs_dir(config_dir) / "routing.jsonl"
    records = _read_jsonl(log_file, last, agent)
    if not records:
        typer.echo("No routing log entries.")
        return
    for r in records:
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        typer.echo(
            f"{ts}  {r.get('agent','?'):<12} {r.get('model','?'):<28} "
            f"{r.get('source','?'):<8} {r.get('prompt_preview','')[:60]}"
        )


@log_app.command("cron")
def log_cron(
    last: Annotated[int, typer.Option("--last", "-n")] = 10,
    job: Annotated[str | None, typer.Option("--job", "-j")] = None,
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Show recent cron run log entries."""
    log_file = _logs_dir(config_dir) / "cron.jsonl"
    records = _read_jsonl(log_file, last, job)
    if not records:
        typer.echo("No cron log entries.")
        return
    for r in records:
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        preview = r.get("output_preview", "")[:80]
        typer.echo(f"{ts}  {r.get('job','?'):<20} [{r.get('status','?')}]  {preview}")


@log_app.command("tail")
def log_tail(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Tail the daemon log file (requires log_file configured)."""
    log_dir = _logs_dir(config_dir)
    routing = log_dir / "routing.jsonl"
    cron = log_dir / "cron.jsonl"
    files = [str(f) for f in (routing, cron) if f.exists()]
    if not files:
        typer.echo("No log files found yet.")
        return
    subprocess.run(["tail", "-f"] + files)


# ---------------------------------------------------------------------------
# arc config
# ---------------------------------------------------------------------------


config_app = typer.Typer(name="config", help="Manage arc configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")


def _config_path(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return Path(config_dir) / "config.yaml"
    cfg = load_config(None)
    return Path(cfg.daemon.pid_file).expanduser().parent / "config.yaml"


@config_app.command("show")
def config_show(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Show current configuration."""
    path = _config_path(config_dir)
    if not path.exists():
        typer.echo("No config file found. Run: arc setup")
        return
    typer.echo(path.read_text())


@config_app.command("edit")
def config_edit(
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Open config in $EDITOR."""
    import os
    path = _config_path(config_dir)
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(path)])


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Dot-notation key (e.g. daemon.auto_start).")],
    value: Annotated[str, typer.Argument(help="Value to set.")],
    config_dir: Annotated[Path | None, typer.Option("--config-dir", hidden=True)] = None,
) -> None:
    """Set a config value using dot-notation."""
    import yaml

    path = _config_path(config_dir)
    if not path.exists():
        typer.echo("No config file found. Run: arc setup", err=True)
        raise typer.Exit(1)

    data = yaml.safe_load(path.read_text()) or {}
    parts = key.split(".")

    # Parse value type
    parsed: bool | int | str
    if value.lower() == "true":
        parsed = True
    elif value.lower() == "false":
        parsed = False
    else:
        try:
            parsed = int(value)
        except ValueError:
            parsed = value

    # Navigate to the parent dict
    node = data
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = parsed

    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    typer.echo(f"Set {key} = {parsed}")


# ---------------------------------------------------------------------------
# arc version
# ---------------------------------------------------------------------------


@app.command("version")
def version_cmd() -> None:
    """Print arc version."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        typer.echo(f"arc {version('arc')}")
    except PackageNotFoundError:
        typer.echo("arc (version unknown)")
