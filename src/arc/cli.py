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
        response = await _ipc.request(cfg, {
            "prompt": job.prompt,
            "agent": job.agent,
            "model": job.model,
            "source": "cron",
        })
        if response is None:
            # Daemon not running - dispatch directly
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
# arc version
# ---------------------------------------------------------------------------


@app.command("version")
def version_cmd() -> None:
    """Print arc version."""
    from arc import __version__
    typer.echo(f"arc {__version__}")
