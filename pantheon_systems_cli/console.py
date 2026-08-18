import typer

_verbose = False


def configure(*, verbose: bool) -> None:
    global _verbose
    _verbose = verbose


def success(message: str, *, verbose_only: bool = False) -> None:
    if verbose_only and not _verbose:
        return
    typer.secho(f"✓ {message}", fg=typer.colors.GREEN)


def error(message: str, *, verbose_only: bool = False) -> None:
    if verbose_only and not _verbose:
        return
        typer.secho(f"✗ {message}", fg=typer.colors.RED, err=True)


def warning(message: str, *, verbose_only: bool = False) -> None:
    if verbose_only and not _verbose:
        return
    typer.secho(f"⚠ {message}", fg=typer.colors.YELLOW)


def info(message: str, *, verbose_only: bool = False) -> None:
    if verbose_only and not _verbose:
        return
    typer.secho(f"ℹ {message}", fg=typer.colors.BLUE)
