from dataclasses import dataclass
from typing import Annotated, Callable

import libvirt  # pyright: ignore[reportMissingTypeStubs]
import typer

import pantheon_systems_cli.console as c
from pantheon_systems_cli.ansible import (
    InventoryError,
    JsonValue,
    get_hosts_from_inventory,
    get_host_variables,
)
from pantheon_systems_cli.bash import run_privileged_script
from pantheon_systems_cli.vm.image import app as image_app

type VmOperation = Callable[[libvirt.virDomain], None]

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
    str,
    typer.Argument(
        help="Canonical machine name from the local Ansible inventory.",
        autocompletion=complete_local_host,
    ),
]


def _get_local_host_variables(host: str) -> dict[str, JsonValue]:
    try:
        return get_host_variables(host, "local")
    except InventoryError as error:
        c.error(str(error))
        raise typer.Exit(1) from error


def _get_vm_settings(host: str) -> VmSettings:
    variables = _get_local_host_variables(host)

    def require_string(name: str) -> str:
        value = variables.get(name)
        if not isinstance(value, str) or not value:
            c.error(f"Host {host!r} requires a non-empty {name!r} variable.")
            raise typer.Exit(1)
        return value

    return VmSettings(
        network=require_string("vm_network"),
        mac=require_string("vm_mac"),
        ip=require_string("vm_ip"),
    )


def _run_vm_operation(
    host: str,
    operation_name: str,
    operation: VmOperation,
) -> None:
    _get_local_host_variables(host)

    try:
        connection = libvirt.open("qemu:///system")
    except libvirt.libvirtError as error:
        c.error(f"Could not connect to system libvirt: {error}")
        raise typer.Exit(1) from error

    try:
        domain = connection.lookupByName(host)
    except libvirt.libvirtError as error:
        if error.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
            c.error(f"{host} does not exist.")
        else:
            c.error(f"Could not find {host}: {error}")

        raise typer.Exit(1) from error

    try:
        operation(domain)
    except libvirt.libvirtError as error:
        c.error(f"Could not {operation_name} {host}: {error}")
        raise typer.Exit(1) from error
    finally:
        connection.close()


@app.command()
def create(host: LocalHost) -> None:
    """Create and start the local VM."""

    settings = _get_vm_settings(host)
    run_privileged_script(
        "set_up_vm.sh",
        (host, settings.network, settings.mac, settings.ip),
    )


@app.command()
def destroy(host: LocalHost) -> None:
    """Remove the VM and disk."""

    _get_local_host_variables(host)
    run_privileged_script("destroy_vm.sh", (host,))


@app.command()
def start(host: LocalHost) -> None:
    """Start an existing VM."""

    def operation(domain: libvirt.virDomain) -> None:
        if domain.isActive():
            c.info(f"{host} is already running.")
            return

        domain.create()
        c.success(f"{host} started.")

    _run_vm_operation(host, "start", operation)


@app.command()
def restart(host: LocalHost) -> None:
    """Restart a running VM."""

    def operation(domain: libvirt.virDomain) -> None:
        if not domain.isActive():
            c.info(f"{host} is stopped; starting it.")
            domain.create()
        else:
            domain.reboot()

        c.success(f"{host} restarted.")

    _run_vm_operation(host, "restart", operation)


@app.command()
def shutdown(
    host: LocalHost,
    force: bool = typer.Option(
        False, "--force", "-f", help="Immediately stop a running VM."
    ),
) -> None:
    """Gracefully shut down a running VM."""

    def operation(domain: libvirt.virDomain) -> None:
        if not domain.isActive():
            c.info(f"{host} is already stopped.")
            return
        if force:
            domain.destroy()
            c.success(f"{host} forcibly stopped.")
        else:
            domain.shutdown()
            c.success(f"{host} is shutting down.")

    _run_vm_operation(host, "shut down", operation)


@app.command()
def state(host: LocalHost) -> None:
    """Get the current state of the machine."""

    def operation(domain: libvirt.virDomain) -> None:
        if not domain.isActive():
            c.info(f"{host} is stopped.")
        else:
            c.success(f"{host} is running.")

    _run_vm_operation(host, "get state of", operation)
