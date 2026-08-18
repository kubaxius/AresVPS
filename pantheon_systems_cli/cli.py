import typer

from pantheon_systems_cli.vm.cli import app as vm_app

app = typer.Typer(
    help="Manage Pantheon systems.",
    no_args_is_help=True,
)

app.add_typer(vm_app, name="vm")


def main() -> None:
    app()
