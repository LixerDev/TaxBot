"""
Reporter — generates CSV and PDF tax reports from a TaxSummary.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from src.models import TaxSummary, GainType, TxType
from src.logger import get_logger

logger = get_logger(__name__)
console = Console()


def render_terminal_summary(summary: TaxSummary):
    """Display a formatted summary table in the terminal."""
    console.print()
    console.rule(f"[bold]🧾 TaxBot Report — Fiscal Year {summary.year}[/bold]")
    console.print(f"[dim]Wallets: {len(summary.wallets)} | Method: {summary.method.upper()}[/dim]\n")

    # Main summary panel
    s_table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    s_table.add_column("Category", width=30, style="dim")
    s_table.add_column("Amount", justify="right")

    def row(label, value, color="white"):
        s_table.add_row(label, f"[{color}]{value}[/{color}]")

    row("Total Proceeds",        f"${summary.total_proceeds:,.2f}", "white")
    row("Total Cost Basis",      f"${summary.total_cost_basis:,.2f}", "white")
    s_table.add_row("", "")
    net = summary.total_gain_loss
    net_color = "green" if net >= 0 else "red"
    row("Net Realized Gain/Loss", f"${net:+,.2f}", net_color)
    s_table.add_row("", "")
    row("  Short-Term Gains",    f"${summary.short_term_gains:,.2f}", "yellow")
    row("  Short-Term Losses",   f"${summary.short_term_losses:,.2f}", "green" if summary.short_term_losses <= 0 else "red")
    row("  Long-Term Gains",     f"${summary.long_term_gains:,.2f}", "yellow")
    row("  Long-Term Losses",    f"${summary.long_term_losses:,.2f}", "green" if summary.long_term_losses <= 0 else "red")
    s_table.add_row("", "")
    row("Staking / Rewards Income", f"${summary.total_staking_income:,.2f}", "cyan")
    row("Deductible TX Fees",    f"-${summary.total_deductible_fees:,.2f}", "green")
    s_table.add_row("", "")
    row("Taxable Events",        str(len(summary.taxable_events)))
    row("Unrealized Lots",       str(len(summary.unrealized_lots)))

    console.print(Panel(s_table, title="[bold]💰 Summary[/bold]", border_style="blue"))

    # Per-token breakdown
    per_token = summary.per_token_summary()
    if per_token:
        t_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        t_table.add_column("Token", style="bold")
        t_table.add_column("Events", justify="right")
        t_table.add_column("Proceeds", justify="right")
        t_table.add_column("Cost Basis", justify="right")
        t_table.add_column("Gain/Loss", justify="right")

        for token in sorted(per_token.values(), key=lambda x: -abs(x["gain_loss"])):
            gl = token["gain_loss"]
            color = "green" if gl >= 0 else "red"
            t_table.add_row(
                token["symbol"],
                str(token["events"]),
                f"${token['proceeds']:,.2f}",
                f"${token['cost_basis']:,.2f}",
                f"[{color}]${gl:+,.2f}[/{color}]",
            )

        console.print(Panel(t_table, title="[bold]📊 Per-Token Breakdown[/bold]", border_style="dim"))

    console.print()


def export_csv(summary: TaxSummary, output_dir: str) -> str:
    """Export taxable events to CSV."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = path / f"tax_report_{summary.year}.csv"

    fieldnames = [
        "Date", "Type", "Token", "Amount",
        "Proceeds (USD)", "Cost Basis (USD)", "Gain/Loss (USD)",
        "Gain Type", "Acquisition Date", "Protocol", "TX Signature"
    ]

    rows = []

    # Taxable events
    for event in sorted(summary.taxable_events, key=lambda e: e.date):
        rows.append(event.to_csv_row())

    # Income events
    for event in sorted(summary.income_events, key=lambda e: e.date):
        rows.append({
            "Date": event.date.strftime("%Y-%m-%d %H:%M:%S"),
            "Type": event.tx_type.value,
            "Token": event.symbol,
            "Amount": round(event.amount_disposed, 8),
            "Proceeds (USD)": round(event.income_usd, 2),
            "Cost Basis (USD)": 0,
            "Gain/Loss (USD)": round(event.income_usd, 2),
            "Gain Type": "INCOME",
            "Acquisition Date": "",
            "Protocol": event.protocol,
            "TX Signature": event.tx_signature[:20] + "...",
        })

    # Fee events
    for event in sorted(summary.fee_events, key=lambda e: e.date):
        rows.append({
            "Date": event.date.strftime("%Y-%m-%d %H:%M:%S"),
            "Type": "NETWORK_FEE",
            "Token": "SOL",
            "Amount": round(event.fee_sol, 8),
            "Proceeds (USD)": "",
            "Cost Basis (USD)": "",
            "Gain/Loss (USD)": f"-{event.fee_usd:.2f}",
            "Gain Type": "DEDUCTIBLE",
            "Acquisition Date": "",
            "Protocol": event.protocol,
            "TX Signature": event.tx_signature[:20] + "...",
        })

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"CSV exported: {filename}")
    return str(filename)


def export_pdf(summary: TaxSummary, output_dir: str) -> str:
    """Export a professional PDF tax report."""
    try:
        from fpdf import FPDF
    except ImportError:
        logger.error("fpdf2 not installed. Run: pip install fpdf2")
        return ""

    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = str(path / f"tax_report_{summary.year}.pdf")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Cover / Header ──────────────────────────────────────
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(30, 30, 60)
    pdf.cell(0, 12, "TaxBot — Crypto Tax Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, f"Fiscal Year {summary.year}  |  Method: {summary.method.upper()}", ln=True, align="C")
    pdf.cell(0, 6, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", ln=True, align="C")
    pdf.ln(6)

    # Wallets
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    for w in summary.wallets:
        pdf.cell(0, 5, f"Wallet: {w}", ln=True, align="C")
    pdf.ln(8)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    # ── Executive Summary ────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(30, 30, 60)
    pdf.cell(0, 8, "Summary", ln=True)
    pdf.ln(2)

    def summary_row(label, value, bold=False, color=(0, 0, 0)):
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.set_text_color(*color)
        pdf.cell(110, 7, label)
        pdf.cell(0, 7, value, ln=True, align="R")

    summary_row("Total Proceeds", f"${summary.total_proceeds:,.2f}")
    summary_row("Total Cost Basis", f"${summary.total_cost_basis:,.2f}")
    net = summary.total_gain_loss
    net_color = (0, 140, 0) if net >= 0 else (180, 0, 0)
    summary_row("Net Realized Gain/Loss", f"${net:+,.2f}", bold=True, color=net_color)
    pdf.ln(2)
    summary_row("  Short-Term Gains", f"${summary.short_term_gains:,.2f}")
    summary_row("  Short-Term Losses", f"${summary.short_term_losses:,.2f}")
    summary_row("  Long-Term Gains", f"${summary.long_term_gains:,.2f}")
    summary_row("  Long-Term Losses", f"${summary.long_term_losses:,.2f}")
    pdf.ln(2)
    summary_row("Staking / Rewards Income", f"${summary.total_staking_income:,.2f}")
    summary_row("Deductible TX Fees", f"-${summary.total_deductible_fees:,.2f}", color=(0, 130, 0))
    pdf.ln(4)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    # ── Per-Token Breakdown ──────────────────────────────────
    per_token = summary.per_token_summary()
    if per_token:
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(30, 30, 60)
        pdf.cell(0, 8, "Per-Token Breakdown", ln=True)
        pdf.ln(2)

        # Table header
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(230, 235, 245)
        pdf.set_text_color(30, 30, 60)
        pdf.cell(35, 7, "Token", border=1, fill=True)
        pdf.cell(20, 7, "Events", border=1, fill=True, align="C")
        pdf.cell(45, 7, "Proceeds", border=1, fill=True, align="R")
        pdf.cell(45, 7, "Cost Basis", border=1, fill=True, align="R")
        pdf.cell(0, 7, "Gain/Loss", border=1, fill=True, align="R", ln=True)

        pdf.set_font("Helvetica", "", 9)
        for token in sorted(per_token.values(), key=lambda x: -abs(x["gain_loss"])):
            gl = token["gain_loss"]
            pdf.set_text_color(0, 130, 0) if gl >= 0 else pdf.set_text_color(180, 0, 0)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(35, 6, token["symbol"][:12], border=1)
            pdf.cell(20, 6, str(token["events"]), border=1, align="C")
            pdf.cell(45, 6, f"${token['proceeds']:,.2f}", border=1, align="R")
            pdf.cell(45, 6, f"${token['cost_basis']:,.2f}", border=1, align="R")
            color = (0, 130, 0) if gl >= 0 else (180, 0, 0)
            pdf.set_text_color(*color)
            pdf.cell(0, 6, f"${gl:+,.2f}", border=1, align="R", ln=True)
            pdf.set_text_color(0, 0, 0)

        pdf.ln(8)

    # ── Transaction List ─────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(30, 30, 60)
    pdf.cell(0, 8, f"Taxable Events ({len(summary.taxable_events)} total)", ln=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 235, 245)
    pdf.cell(28, 6, "Date", border=1, fill=True)
    pdf.cell(18, 6, "Type", border=1, fill=True)
    pdf.cell(18, 6, "Token", border=1, fill=True)
    pdf.cell(32, 6, "Proceeds", border=1, fill=True, align="R")
    pdf.cell(32, 6, "Cost Basis", border=1, fill=True, align="R")
    pdf.cell(32, 6, "Gain/Loss", border=1, fill=True, align="R")
    pdf.cell(0, 6, "Term", border=1, fill=True, align="C", ln=True)

    pdf.set_font("Helvetica", "", 7)
    for event in sorted(summary.taxable_events, key=lambda e: e.date)[:200]:
        gl = event.gain_loss_usd
        pdf.set_text_color(0, 0, 0)
        pdf.cell(28, 5, event.date.strftime("%Y-%m-%d %H:%M"), border=1)
        pdf.cell(18, 5, event.tx_type.value[:10], border=1)
        pdf.cell(18, 5, event.symbol[:8], border=1)
        pdf.cell(32, 5, f"${event.proceeds_usd:,.2f}", border=1, align="R")
        pdf.cell(32, 5, f"${event.cost_basis_usd:,.2f}", border=1, align="R")
        color = (0, 130, 0) if gl >= 0 else (180, 0, 0)
        pdf.set_text_color(*color)
        pdf.cell(32, 5, f"${gl:+,.2f}", border=1, align="R")
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 5, event.gain_type.value[:2], border=1, align="C", ln=True)

    # Footer
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.multi_cell(
        0, 5,
        "⚠️ DISCLAIMER: This report is generated by TaxBot for informational purposes only and does not "
        "constitute tax, legal, or financial advice. Always consult a qualified tax professional or CPA "
        "before filing your tax return. Accuracy depends on the completeness of transaction data and "
        "availability of historical price data.",
        align="C"
    )

    pdf.output(filename)
    logger.info(f"PDF exported: {filename}")
    return filename
