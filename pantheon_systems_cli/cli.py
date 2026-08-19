import typer
from pantheon_systems_cli import console
from pantheon_systems_cli.vm.cli import app as vm_app
from pantheon_systems_cli.ansible.cli import app as ansible_app

app = typer.Typer(
    help="Manage Pantheon systems.",
    no_args_is_help=True,
)

app.add_typer(vm_app, name="vm")
app.add_typer(ansible_app, name="ans")


@app.callback()
def configure_application(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed output.",
    ),
) -> None:
    console.configure(verbose=verbose)


def main() -> None:
    app()
