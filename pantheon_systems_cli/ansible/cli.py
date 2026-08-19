from pathlib import Path
import subprocess
from typing import Annotated

import typer
from pantheon_systems_cli.ansible.completion import complete_roles
import pantheon_systems_cli.console as c
from pantheon_systems_cli.config import (
    ANSIBLE_ROLES_PATH,
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


# temporary annoying warning supression
_PROTOMATTER_WARNING = (
    "Collection at "
    "'/usr/lib/python3.14/site-packages/ansible/_internal/"
    "ansible_collections/ansible/_protomatter' "
    "does not have a MANIFEST.json file, nor has it galaxy.yml: "
    "cannot detect version."
)


def _run_ansible_doc(*arguments: object) -> None:
    result = subprocess.run(
        ["ansible-doc", *map(str, arguments)],
        text=True,
        stderr=subprocess.PIPE,
    )

    for line in result.stderr.splitlines():
        if _PROTOMATTER_WARNING not in line:
            typer.echo(line, err=True)

    if result.returncode != 0:
        raise typer.Exit(result.returncode)


@app.command()
def play(prod: ProdFlag = False) -> None:
    """Run the main ansible playbook against either local or prod."""
    if prod:
        typer.confirm(
            (
                "Are you sure that you want to run "
                "the playbook against the prod environment?"
            ),
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


@app.command()
def rdoc(
    role: Annotated[
        str | None,
        typer.Argument(
            help="Role whose documentation should be displayed.",
            autocompletion=complete_roles,
        ),
    ] = None,
):
    """Print docs for a given role or print all roles with short descriptions."""
    if role is None:
        _run_ansible_doc("-t", "role", "-r", ANSIBLE_ROLES_PATH, "-l")
    else:
        _run_ansible_doc("-t", "role", "-r", ANSIBLE_ROLES_PATH, role)
