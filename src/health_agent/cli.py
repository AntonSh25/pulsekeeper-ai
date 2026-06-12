import typer

from health_agent.domain import parse_health_log

app = typer.Typer(help="Health Agent CLI")


@app.command()
def parse(text: str) -> None:
    """Parse a free-text health log and print structured JSON."""
    typer.echo(parse_health_log(text).model_dump_json())
