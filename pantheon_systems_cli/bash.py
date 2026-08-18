import os
import subprocess
from typing import Sequence

import typer

import pantheon_systems_cli.console as c
from pantheon_systems_cli.config import SCRIPTS_PATH


def run_privileged_script(filename: str, args: Sequence[str] = ()) -> None:
    script = SCRIPTS_PATH / filename

    command = [str(script), *args]
    # if user is not root, use sudo
    if os.geteuid() != 0:
        command = ["sudo", "--", *command]

    try:
        # Inherit the terminal so sudo and shell prompts work normally.
        subprocess.run(command, check=True)
    except FileNotFoundError as error:
        c.error(f"Could not execute command: {error}")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as error:
        raise typer.Exit(error.returncode)
