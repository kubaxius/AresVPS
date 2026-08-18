from dataclasses import dataclass
from typing import Annotated, Callable

import libvirt  # pyright: ignore[reportMissingTypeStubs]
import typer

import pantheon_systems_cli.console as c
from pantheon_systems_cli.ansible import (
    InventoryError,
    JsonValue,
    get_hosts_from_inventory,
    get_inventory_host_variables,
)
from pantheon_systems_cli.bash import run_privileged_script
from pantheon_systems_cli.vm.image import app as image_app

type VmOperation = Callable[[str, libvirt.virDomain], None]
type VmCommand = Callable[["VmTarget"], None]

app = typer.Typer(
    help="Manage virtual machines.",
    no_args_is_help=True,
)

app.add_typer(image_app, name="image")


@dataclass(frozen=True)
class VmSettings:
    network: str
    mac: str
    ip: str


@dataclass(frozen=True)
class VmTarget:
    host: str
    variables: dict[str, JsonValue]


def _ignore_libvirt_error(
    _context: object,
    _error: tuple[object, ...],
) -> None:
    pass


libvirt.registerErrorHandler(_ignore_libvirt_error, None)


def complete_local_host(incomplete: str) -> list[str]:
    """
    Complete canonical machine names from the local inventory
    for use in autocompletion.
    """

    try:
        hosts = get_hosts_from_inventory("local")
    except InventoryError:
        return []

    return [host for host in hosts if host.startswith(incomplete)]


LocalHost = Annotated[
    str | None,
    typer.Argument(
        help="Canonical machine name from the local inventory; omit with --all.",
        autocompletion=complete_local_host,
    ),
]

AllVms = Annotated[
    bool,
    typer.Option(
        "--all",
        help="Apply the command to every VM in the local inventory.",
    ),
]


def _resolve_targets(host: str | None, all_hosts: bool) -> list[VmTarget]:
    if (host is not None) == all_hosts:
        raise typer.BadParameter("Specify exactly one of HOST or --all.")

    try:
        host_variables = get_inventory_host_variables("local")
    except InventoryError as error:
        c.error(str(error))
        raise typer.Exit(1) from error

    if not host_variables:
        c.error("The local inventory does not contain any hosts.")
        raise typer.Exit(1)

    if host is not None:
        variables = host_variables.get(host)
        if variables is None:
            c.error(f"Host {host!r} is not in the 'local' inventory")
            raise typer.Exit(1)
        return [VmTarget(host, variables)]

    return [VmTarget(name, host_variables[name]) for name in sorted(host_variables)]


def _get_vm_settings(target: VmTarget) -> VmSettings:
    host = target.host

    def require_string(name: str) -> str:
        value = target.variables.get(name)
        if not isinstance(value, str) or not value:
            c.error(f"Host {host!r} requires a non-empty {name!r} variable.")
            raise typer.Exit(1)
        return value

    return VmSettings(
        network=require_string("vm_network"),
        mac=require_string("vm_mac"),
        ip=require_string("vm_ip"),
    )


def _report_bulk_failures(failed_hosts: list[str]) -> None:
    if not failed_hosts:
        return

    c.error(
        f"Operation failed for {len(failed_hosts)} VM(s): {', '.join(failed_hosts)}"
    )
    raise typer.Exit(1)


def _run_commands(
    targets: list[VmTarget],
    command: VmCommand,
    *,
    continue_on_error: bool,
) -> None:
    if not continue_on_error:
        command(targets[0])
        return

    failed_hosts: list[str] = []
    for target in targets:
        try:
            command(target)
        except typer.Exit as error:
            if error.exit_code != 0:
                failed_hosts.append(target.host)

    _report_bulk_failures(failed_hosts)


def _run_vm_operations(
    targets: list[VmTarget],
    operation_name: str,
    operation: VmOperation,
    *,
    continue_on_error: bool,
) -> None:
    try:
        connection = libvirt.open("qemu:///system")
    except libvirt.libvirtError as error:
        c.error(f"Could not connect to system libvirt: {error}")
        raise typer.Exit(1) from error

    failed_hosts: list[str] = []
    try:
        for target in targets:
            host = target.host
            try:
                domain = connection.lookupByName(host)
            except libvirt.libvirtError as error:
                if error.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                    c.error(f"{host} does not exist.")
                else:
                    c.error(f"Could not find {host}: {error}")

                if not continue_on_error:
                    raise typer.Exit(1) from error
                failed_hosts.append(host)
                continue

            try:
                operation(host, domain)
            except libvirt.libvirtError as error:
                c.error(f"Could not {operation_name} {host}: {error}")
                if not continue_on_error:
                    raise typer.Exit(1) from error
                failed_hosts.append(host)
    finally:
        connection.close()

    _report_bulk_failures(failed_hosts)


def _create_vm(target: VmTarget) -> None:
    settings = _get_vm_settings(target)
    run_privileged_script(
        "set_up_vm.sh",
        (target.host, settings.network, settings.mac, settings.ip),
    )


def _destroy_vm(target: VmTarget, *, assume_yes: bool) -> None:
    args = ("--yes", target.host) if assume_yes else (target.host,)
    run_privileged_script("destroy_vm.sh", args)


def _start_vm(host: str, domain: libvirt.virDomain) -> None:
    if domain.isActive():
        c.info(f"{host} is already running.")
        return

    domain.create()
    c.success(f"{host} started.")


def _restart_vm(host: str, domain: libvirt.virDomain) -> None:
    if not domain.isActive():
        c.info(f"{host} is stopped; starting it.")
        domain.create()
    else:
        domain.reboot()

    c.success(f"{host} restarted.")


def _shutdown_vm(host: str, domain: libvirt.virDomain, *, force: bool) -> None:
    if not domain.isActive():
        c.info(f"{host} is already stopped.")
        return
    if force:
        domain.destroy()
        c.success(f"{host} forcibly stopped.")
    else:
        domain.shutdown()
        c.success(f"{host} is shutting down.")


def _show_vm_state(host: str, domain: libvirt.virDomain) -> None:
    if not domain.isActive():
        c.info(f"{host} is stopped.")
    else:
        c.success(f"{host} is running.")


@app.command()
def create(host: LocalHost = None, all_hosts: AllVms = False) -> None:
    """Create and start one or all local VMs."""

    targets = _resolve_targets(host, all_hosts)
    _run_commands(
        targets,
        _create_vm,
        continue_on_error=all_hosts,
    )


@app.command()
def destroy(host: LocalHost = None, all_hosts: AllVms = False) -> None:
    """Remove one or all VMs and their disks."""

    targets = _resolve_targets(host, all_hosts)
    if all_hosts:
        c.warning("The following VMs and their disks will be destroyed:")
        for target in targets:
            typer.echo(f"  - {target.host}")
        if not typer.confirm("Continue?", default=False):
            c.info("Cancelled.")
            return

    _run_commands(
        targets,
        lambda target: _destroy_vm(target, assume_yes=all_hosts),
        continue_on_error=all_hosts,
    )


@app.command()
def start(host: LocalHost = None, all_hosts: AllVms = False) -> None:
    """Start one or all existing VMs."""

    targets = _resolve_targets(host, all_hosts)
    _run_vm_operations(
        targets,
        "start",
        _start_vm,
        continue_on_error=all_hosts,
    )


@app.command()
def restart(host: LocalHost = None, all_hosts: AllVms = False) -> None:
    """Restart one or all VMs."""

    targets = _resolve_targets(host, all_hosts)
    _run_vm_operations(
        targets,
        "restart",
        _restart_vm,
        continue_on_error=all_hosts,
    )


@app.command()
def shutdown(
    host: LocalHost = None,
    all_hosts: AllVms = False,
    force: bool = typer.Option(
        False, "--force", "-f", help="Immediately stop a running VM."
    ),
) -> None:
    """Gracefully shut down one or all running VMs."""

    targets = _resolve_targets(host, all_hosts)
    _run_vm_operations(
        targets,
        "shut down",
        lambda name, domain: _shutdown_vm(name, domain, force=force),
        continue_on_error=all_hosts,
    )


@app.command()
def state(host: LocalHost = None, all_hosts: AllVms = False) -> None:
    """Get the current state of one or all VMs."""

    targets = _resolve_targets(host, all_hosts)
    _run_vm_operations(
        targets,
        "get state of",
        _show_vm_state,
        continue_on_error=all_hosts,
    )
