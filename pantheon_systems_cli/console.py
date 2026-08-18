import typer


def success(message: str, *, show: bool = True) -> None:
    if show:
        typer.secho(f"✓ {message}", fg=typer.colors.GREEN)


def error(message: str, *, show: bool = True) -> None:
    if show:
        typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)


def warning(message: str, *, show: bool = True) -> None:
    if show:
        typer.secho(f"⚠ {message}", fg=typer.colors.YELLOW)


def info(message: str, *, show: bool = True) -> None:
    if show:
        typer.secho(f"ℹ {message}", fg=typer.colors.BLUE)
