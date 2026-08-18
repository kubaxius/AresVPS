import typer

from pantheon_systems_cli.vm.image import is_image_up_to_date

app = typer.Typer()


@app.command()
def test() -> None:
    is_image_up_to_date()


@app.command()
def test2(test: str) -> None:
    print(test)


# Planned tools:
#   vm-create - downloads and installs the vm
#   vm-destroy - destroys the vm
#   ans-run - runs the site.yml playbook
#   ans-doc - print roles and their descriptions
#   and-doc {ROLE} - show role docs
#
#   ans-run and similar commands should accept --prod flag to be able to run on prod machines.
def main() -> None:
    app()
    print("Hello from pantheon-systems!")
