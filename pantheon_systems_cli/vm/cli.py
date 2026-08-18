import libvirt  # pyright: ignore[reportMissingTypeStubs]
import typer

import pantheon_systems_cli.console as c
from pantheon_systems_cli.bash import run_privileged_script
from pantheon_systems_cli.vm.image import app as image_app

app = typer.Typer(
    help="Manage virtual machines.",
    no_args_is_help=True,
)

app.add_typer(image_app, name="image")


@app.command()
def setup() -> None:
    """Create and start the local VM."""
    run_privileged_script("set_up_vm.sh")


@app.command()
def destroy() -> None:
    """Remove the VM and disk."""
    run_privileged_script("destroy_vm.sh")


@app.command()
def start(name: str = "ares-local") -> None:
    """Start an existing VM."""

    try:
        connection = libvirt.open("qemu:///system")
    except libvirt.libvirtError as error:
        c.error(f"Could not connect to system libvirt: {error}")
        raise typer.Exit(1) from error

    try:
        domain = connection.lookupByName(name)

        if domain.isActive():
            c.info(f"{name} is already running.")
            return

        domain.create()
        c.success(f"{name} started.")
    except libvirt.libvirtError as error:
        c.error(f"Could not start {name}: {error}")
        raise typer.Exit(1) from error
    finally:
        connection.close()
