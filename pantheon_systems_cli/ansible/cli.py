from pathlib import Path
import subprocess
from typing import Annotated

import typer
import pantheon_systems_cli.console as c
from pantheon_systems_cli.config import (
    LOCAL_INVENTORY_PATH,
    PLAYBOOK_PATH,
    PROD_INVENTORY_PATH,
)


class AnsibleError(Exception):
    pass


ProdFlag = Annotated[
    bool,
    typer.Option(
        "--prod",
        "--production",
        "-p",
        help=(
            "Add this to run the commands against production environment."
            " If it is not provided, the commands will run against local environment."
        ),
    ),
]


app = typer.Typer(
    help="Run ansible commands.",
    no_args_is_help=True,
)


def _run_playbook(inventory_path: Path):
    try:
        subprocess.run(
            ["ansible-playbook", "-i", str(inventory_path), PLAYBOOK_PATH],
            check=True,
        )
    except FileNotFoundError as error:
        raise AnsibleError("ansible is not installed") from error
    except subprocess.CalledProcessError as error:
        raise AnsibleError("Ansible execution failed") from error


@app.command()
def play(prod: ProdFlag = False) -> None:
    if prod:
        typer.confirm(
            "Are you sure that you want to run the playbook against the prod environment?",
            abort=True,
        )
        inventory_path = PROD_INVENTORY_PATH
    else:
        inventory_path = LOCAL_INVENTORY_PATH

    try:
        _run_playbook(inventory_path)
    except AnsibleError as err:
        c.error(f"{err}")
        typer.Exit(1)
    else:
        c.success("Playbook successfully applied!")
