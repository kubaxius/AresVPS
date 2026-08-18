import typer

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
