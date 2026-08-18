import typer

from pantheon_systems_cli.vm.image import app as image_app

app = typer.Typer(
    help="Manage virtual machines.",
    no_args_is_help=True,
)

app.add_typer(image_app, name="image")
