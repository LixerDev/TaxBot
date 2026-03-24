# 🧾 TaxBot

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/d6e3f75c-df12-4fdb-9b35-76ef6297c3de" />


**Built by LixerDev**
Follow me here on my personal Twitter (X): https://x.com/Lix_Devv

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11+-green)
![Solana](https://img.shields.io/badge/network-Solana-9945FF)
![License](https://img.shields.io/badge/license-MIT-purple)

> ⚠️ **Disclaimer:** TaxBot is a calculation tool, not tax advice. Always verify results with a qualified crypto tax professional or CPA before filing.

---

## 📊 What TaxBot Calculates

### Per-Token P&L
| Token | Proceeds | Cost Basis | Gain/Loss | Type |
|---|---|---|---|---|
| SOL | $12,400 | $8,200 | **+$4,200** | Long-term |
| BONK | $340 | $890 | **-$550** | Short-term |
| JUP | $1,100 | $750 | **+$350** | Short-term |

### Summary Report
| Category | Amount |
|---|---|
| Total Proceeds | $13,840 |
| Total Cost Basis | $9,840 |
| **Net Realized Gain** | **+$4,000** |
| Short-Term Gains | $350 |
| Long-Term Gains | $4,200 |
| Short-Term Losses | -$550 |
| Deductible TX Fees | -$14.20 |
| Staking Income | $280 |

### Transaction Types Classified
| Type | Tax Treatment |
|---|---|
| **SWAP** | Taxable event (dispose + acquire) |
| **SELL** | Taxable event (capital gain/loss) |
| **BUY** | Acquire (sets cost basis) |
| **TRANSFER_IN** | Acquire at FMV |
| **TRANSFER_OUT** | Dispose at FMV |
| **STAKING_REWARD** | Ordinary income at FMV |
| **NFT_BUY / NFT_SELL** | Taxable event |
| **NETWORK_FEE** | Deductible expense |

---

## 🚀 Quick Start

```bash
git clone https://github.com/LixerDev/TaxBot.git
cd TaxBot
pip install -r requirements.txt
cp .env.example .env
# Add your Helius API key to .env

# Full tax report for 2024
python main.py report YOUR_WALLET --year 2024

# Summary only (no export)
python main.py summary YOUR_WALLET --year 2024

# Export CSV + PDF
python main.py report YOUR_WALLET --year 2024 --output ./my_tax_report

# Use HIFO method (minimizes taxable gains)
python main.py report YOUR_WALLET --year 2024 --method hifo

# Multiple wallets combined
python main.py report WALLET1 WALLET2 --year 2024

# Show all transactions (not just taxable events)
python main.py txs YOUR_WALLET --year 2024
```

---

## ⚙️ Cost Basis Methods

| Method | Description | Best For |
|---|---|---|
| **FIFO** | First In, First Out (default) | Most jurisdictions require this |
| **LIFO** | Last In, First Out | High-basis recent purchases |
| **HIFO** | Highest In, First Out | Minimizing taxable gains |

> **Note:** Tax authorities in many countries (US, UK, etc.) specify which method is required. Consult your tax professional.

---

## 📄 Report Outputs

### CSV (`tax_report_2024.csv`)
One row per taxable event with:
- Date, Token, Amount, Proceeds, Cost Basis, Gain/Loss, Short/Long Term, Acquisition Date

### PDF (`tax_report_2024.pdf`)
Professional multi-page report with:
- Executive summary table
- Per-token breakdown
- Full transaction list
- Deductible fees section
- Staking income section

---

## ⚙️ Configuration

| Variable | Description | Required |
|---|---|---|
| `HELIUS_API_KEY` | Helius API for enhanced tx data | ✅ |
| `BIRDEYE_API_KEY` | Historical price data | Optional |
| `COST_BASIS_METHOD` | fifo / lifo / hifo (default: fifo) | No |
| `BASE_CURRENCY` | USD, EUR, GBP, etc. | No |
| `TAX_YEAR_START` | Fiscal year start month (default: 1 = January) | No |

---

## 🏗️ Architecture

```
main.py (CLI)
    └── Orchestrator
            ├── Fetcher       → Helius API (full tx history, paginated)
            ├── Classifier    → Labels each tx: SWAP, BUY, SELL, STAKE, FEE...
            ├── PriceOracle   → Historical USD price at tx time (Birdeye)
            ├── CostBasis     → FIFO/LIFO/HIFO lot management engine
            ├── PnLCalc       → Computes realized gains, income, fees
            ├── Database      → SQLite cache (avoid re-fetching)
            └── Reporter      → CSV + PDF generation
```

# 🧾 Coin

<img width="1024" height="1024" alt="Adobe Express - file (9)" src="https://github.com/user-attachments/assets/c69b4f34-4fc0-4440-9530-97cda823a6f7" />

