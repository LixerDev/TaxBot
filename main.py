#!/usr/bin/env python3
"""
TaxBot — Solana Crypto Tax Calculator
Built by LixerDev
"""

import asyncio
import json
from typing import Optional
import typer
from rich.console import Console

from config import config
from src.logger import get_logger, print_banner
from src.fetcher import Fetcher
from src.pnl_calculator import PnLCalculator
from src.reporter import render_terminal_summary, export_csv, export_pdf

app = typer.Typer(
    help="TaxBot — Solana crypto tax calculator. Supports FIFO, LIFO, HIFO.",
    no_args_is_help=True
)
console = Console()
logger = get_logger(__name__)


def _validate():
    errors = config.validate()
    if errors:
        for e in errors:
            console.print(f"[red]Config error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def report(
    wallets: list[str] = typer.Argument(..., help="Wallet address(es) to calculate taxes for"),
    year: int = typer.Option(..., "--year", "-y", help="Fiscal year (e.g. 2024)"),
    method: str = typer.Option("fifo", "--method", "-m", help="Cost basis: fifo, lifo, hifo"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output directory for CSV + PDF"),
    csv_only: bool = typer.Option(False, "--csv-only", help="Export CSV only (no PDF)"),
    no_export: bool = typer.Option(False, "--no-export", help="Show summary only, no files"),
):
    """
    Generate a full tax report for one or more wallets.
    Exports CSV and PDF to the output directory.
    """
    print_banner()
    _validate()

    if method not in ("fifo", "lifo", "hifo"):
        console.print("[red]Method must be fifo, lifo, or hifo[/red]")
        raise typer.Exit(1)

    config.COST_BASIS_METHOD = method

    async def _run():
        fetcher = Fetcher()
        calc = PnLCalculator(method=method)

        all_txs = []
        for wallet in wallets:
            console.print(f"[dim]Fetching transactions for {wallet[:12]}... (year {year})[/dim]")
            txs = await fetcher.fetch_transactions(wallet, year)
            all_txs.extend(txs)

        console.print(f"[dim]Total transactions fetched: {len(all_txs)}[/dim]")

        if not all_txs:
            console.print(f"[yellow]No transactions found for year {year}.[/yellow]")
            return

        console.print(f"[dim]Processing with {method.upper()} method...[/dim]")
        summary = await calc.process(list(wallets), all_txs, year)
        render_terminal_summary(summary)

        if not no_export:
            out_dir = output or f"./tax_reports/{year}"
            csv_path = export_csv(summary, out_dir)
            console.print(f"[green]✅ CSV: {csv_path}[/green]")

            if not csv_only:
                pdf_path = export_pdf(summary, out_dir)
                if pdf_path:
                    console.print(f"[green]✅ PDF: {pdf_path}[/green]")
                else:
                    console.print("[yellow]PDF generation skipped (install fpdf2 for PDF support)[/yellow]")

    asyncio.run(_run())


@app.command()
def summary(
    wallets: list[str] = typer.Argument(..., help="Wallet address(es)"),
    year: int = typer.Option(..., "--year", "-y", help="Fiscal year"),
    method: str = typer.Option("fifo", "--method", "-m", help="Cost basis: fifo, lifo, hifo"),
):
    """Quick summary — terminal output only, no files exported."""
    print_banner()
    _validate()

    config.COST_BASIS_METHOD = method

    async def _run():
        fetcher = Fetcher()
        calc = PnLCalculator(method=method)

        all_txs = []
        for wallet in wallets:
            txs = await fetcher.fetch_transactions(wallet, year)
            all_txs.extend(txs)

        if not all_txs:
            console.print(f"[yellow]No transactions found for year {year}.[/yellow]")
            return

        summary = await calc.process(list(wallets), all_txs, year)
        render_terminal_summary(summary)

    asyncio.run(_run())


@app.command()
def txs(
    wallet: str = typer.Argument(..., help="Wallet address"),
    year: int = typer.Option(..., "--year", "-y", help="Fiscal year"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max transactions to show"),
):
    """List classified transactions for a wallet and year."""
    print_banner()
    _validate()

    async def _run():
        from rich.table import Table
        from rich import box as rbox
        from src.classifier import Classifier

        fetcher = Fetcher()
        classifier = Classifier()

        txs = await fetcher.fetch_transactions(wallet, year)
        console.print(f"\n[dim]Found {len(txs)} transactions in {year}[/dim]\n")

        table = Table(box=rbox.SIMPLE, show_header=True)
        table.add_column("Date", width=18)
        table.add_column("Type", width=16)
        table.add_column("Description", width=50)
        table.add_column("Fee (SOL)", justify="right", width=12)

        for tx in txs[:limit]:
            tx_type = classifier.classify(tx, wallet)
            table.add_row(
                tx.date_str[:16],
                tx_type.value,
                (tx.description or "")[:50],
                f"{tx.fee_sol:.6f}",
            )

        console.print(table)

    asyncio.run(_run())


@app.command()
def compare(
    wallet: str = typer.Argument(..., help="Wallet address"),
    year: int = typer.Option(..., "--year", "-y", help="Fiscal year"),
):
    """Compare FIFO, LIFO, and HIFO results side-by-side to find best method."""
    print_banner()
    _validate()

    async def _run():
        from rich.table import Table
        from rich import box as rbox

        fetcher = Fetcher()
        console.print(f"[dim]Fetching transactions for comparison...[/dim]")
        all_txs = await fetcher.fetch_transactions(wallet, year)

        results = {}
        for method in ("fifo", "lifo", "hifo"):
            calc = PnLCalculator(method=method)
            summary = await calc.process([wallet], all_txs, year)
            results[method] = summary

        table = Table(box=rbox.ROUNDED, show_header=True, title=f"Method Comparison — {year}")
        table.add_column("Metric", style="bold", width=30)
        table.add_column("FIFO", justify="right", width=20)
        table.add_column("LIFO", justify="right", width=20)
        table.add_column("HIFO", justify="right", width=20)

        def cmp_row(label, getter):
            vals = [getter(results[m]) for m in ("fifo", "lifo", "hifo")]
            best_idx = vals.index(min(vals))  # Lowest tax liability = best
            cells = []
            for i, v in enumerate(vals):
                color = "green" if i == best_idx else "white"
                cells.append(f"[{color}]${v:+,.2f}[/{color}]")
            table.add_row(label, *cells)

        cmp_row("Net Gain/Loss",      lambda s: s.total_gain_loss)
        cmp_row("Short-Term Gains",   lambda s: s.short_term_gains)
        cmp_row("Long-Term Gains",    lambda s: s.long_term_gains)

        console.print(table)
        console.print("[dim]Green = lowest tax liability for that metric[/dim]\n")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
