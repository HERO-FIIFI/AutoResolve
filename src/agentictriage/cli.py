from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from agentictriage.audit import InMemoryAuditSink
from agentictriage.config import Settings
from agentictriage.fallback import FallbackRouter
from agentictriage.models import RetrievedChunk, TenantPolicy, Ticket
from agentictriage.pipeline import TriagePipeline

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Operate and test AgenticTriage-AI."""


@app.command()
def run(
    ticket: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    kb: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    allow_lmstudio: Annotated[
        bool,
        typer.Option(help="Explicitly allow the local LM Studio provider for this run."),
    ] = False,
) -> None:
    ticket_value = Ticket.model_validate_json(ticket.read_text(encoding="utf-8"))
    chunks = [
        RetrievedChunk.model_validate(item) for item in json.loads(kb.read_text(encoding="utf-8"))
    ]
    policy = TenantPolicy(
        tenant_id=ticket_value.tenant_id,
        allowed_providers=frozenset({"lmstudio"} if allow_lmstudio else set()),
        allowed_regions=frozenset({"local"} if allow_lmstudio else set()),
    )
    pipeline = TriagePipeline(
        FallbackRouter(Settings.from_environment().providers()), InMemoryAuditSink()
    )
    result = asyncio.run(
        pipeline.process(
            ticket_value,
            correlation_id=str(uuid4()),
            policy=policy,
            knowledge_base=chunks,
        )
    )
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
