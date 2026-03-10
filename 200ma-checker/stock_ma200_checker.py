import warnings
from datetime import datetime

import pandas as pd
import yfinance as yf
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

warnings.filterwarnings("ignore")

console = Console()

# S&P 100 constituents (OEX)
SP100_TICKERS = [
    "AAPL",
    "ABBV",
    "ABT",
    "ACN",
    "ADBE",
    "AIG",
    "AMD",
    "AMGN",
    "AMT",
    "AMZN",
    "AON",
    "APA",
    "APD",
    "APH",
    "AVGO",
    "AXP",
    "BA",
    "BAC",
    "BIIB",
    "BK",
    "BKNG",
    "BLK",
    "BMY",
    "BRK-B",
    "C",
    "CAT",
    "CHTR",
    "CL",
    "CMCSA",
    "COF",
    "COP",
    "COST",
    "CRM",
    "CSCO",
    "CVS",
    "CVX",
    "D",
    "DD",
    "DE",
    "DHR",
    "DIS",
    "DOW",
    "DUK",
    "EMR",
    "EXC",
    "F",
    "FDX",
    "GD",
    "GE",
    "GILD",
    "GM",
    "GOOG",
    "GOOGL",
    "GS",
    "HAL",
    "HD",
    "HON",
    "IBM",
    "INTC",
    "INTU",
    "JNJ",
    "JPM",
    "KHC",
    "KMI",
    "KO",
    "LIN",
    "LLY",
    "LMT",
    "LOW",
    "MA",
    "MCD",
    "MDLZ",
    "MDT",
    "MET",
    "META",
    "MMM",
    "MO",
    "MRK",
    "MS",
    "MSFT",
    "NEE",
    "NFLX",
    "NKE",
    "NOW",
    "NVDA",
    "ORCL",
    "OXY",
    "PEP",
    "PFE",
    "PG",
    "PM",
    "PYPL",
    "QCOM",
    "RTX",
    "SBUX",
    "SCHW",
    "SO",
    "SPG",
    "T",
    "TGT",
    "TMO",
    "TMUS",
    "TXN",
    "UNH",
    "UNP",
    "UPS",
    "USB",
    "V",
    "VZ",
    "WFC",
    "WMT",
    "XOM",
]

# Taiwan 50 constituents (0050 holdings - major ones with Yahoo Finance tickers)
TW50_TICKERS = [
    "2330.TW",  # TSMC
    "2317.TW",  # Hon Hai
    "2454.TW",  # MediaTek
    "2308.TW",  # Delta Electronics
    "2303.TW",  # UMC
    "2412.TW",  # Chunghwa Telecom
    "2882.TW",  # Cathay Financial
    "2881.TW",  # Fubon Financial
    "2886.TW",  # Mega Financial
    "1301.TW",  # Formosa Plastics
    "1303.TW",  # Nan Ya Plastics
    "1326.TW",  # Formosa Chemicals
    "2002.TW",  # China Steel
    "2891.TW",  # CTBC Financial
    "2884.TW",  # E.Sun Financial
    "3711.TW",  # ASE Technology
    "2892.TW",  # First Financial
    "5880.TW",  # Chailease Holding
    "2885.TW",  # Yuanta Financial
    "2883.TW",  # China Development
    "2880.TW",  # Hua Nan Financial
    "1216.TW",  # Uni-President
    "2887.TW",  # Taishin Financial
    "2890.TW",  # Sinopac Financial
    "2207.TW",  # Hotai Motor
    "3045.TW",  # Taiwan Mobile
    "4904.TW",  # Far EasTone
    "2357.TW",  # ASUS
    "2382.TW",  # Quanta Computer
    "2379.TW",  # Realtek
    "2395.TW",  # Advantech
    "2345.TW",  # Accton Technology
    "3008.TW",  # Largan Precision
    "2327.TW",  # Yageo
    "3034.TW",  # Novatek Microelectronics
    "2376.TW",  # Gigabyte Technology
    "2408.TW",  # Nanya Technology
    "6505.TW",  # Formosa Petrochemical
    "1402.TW",  # Far Eastern New Century
    "2301.TW",  # Lite-On Technology
    "2474.TW",  # Catcher Technology
    "4938.TW",  # Pegatron
    "2353.TW",  # Acer
    "2324.TW",  # Compal Electronics
    "2347.TW",  # Synnex Technology
    "1101.TW",  # Taiwan Cement
    "2105.TW",  # Cheng Shin Rubber
    "9910.TW",  # Feng Tay Enterprises
    "2609.TW",  # Yang Ming Marine
]


def get_stock_data(ticker: str, period: str = "1y") -> dict | None:
    """Fetch stock data and calculate 200MA."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")

        if hist.empty or len(hist) < 50:
            return None

        current_price = hist["Close"].iloc[-1]
        ma200 = hist["Close"].rolling(window=200).mean().iloc[-1]

        # If we don't have 200 days, use what we have (e.g. 252 trading days ~ 1 year)
        if pd.isna(ma200):
            ma200 = hist["Close"].mean()

        diff = current_price - ma200
        diff_pct = (diff / ma200) * 100

        # Get company name
        info = stock.fast_info
        try:
            name = stock.info.get("shortName", ticker)
        except:
            name = ticker

        return {
            "ticker": ticker,
            "name": name,
            "price": current_price,
            "ma200": ma200,
            "diff": diff,
            "diff_pct": diff_pct,
            "below_ma200": current_price < ma200,
        }
    except Exception:
        return None


def fetch_all(tickers: list[str], label: str) -> list[dict]:
    results = []
    total = len(tickers)

    with console.status(f"[cyan]Fetching {label} data...[/cyan]") as status:
        for i, ticker in enumerate(tickers, 1):
            status.update(f"[cyan]Fetching {label}: {ticker} ({i}/{total})[/cyan]")
            data = get_stock_data(ticker)
            if data:
                results.append(data)

    return results


def build_table(results: list[dict], title: str, currency: str = "USD") -> Table:
    below = [r for r in results if r["below_ma200"]]
    below.sort(key=lambda x: x["diff_pct"])  # worst first

    table = Table(
        title=f"[bold red]📉 {title}[/bold red]\n[dim]{len(below)} / {len(results)} stocks below 200MA[/dim]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white on dark_blue",
        border_style="blue",
        expand=False,
    )

    table.add_column("Ticker", style="cyan bold", width=12)
    table.add_column("Company", style="white", width=28)
    table.add_column(f"Price ({currency})", justify="right", style="yellow", width=14)
    table.add_column(f"200MA ({currency})", justify="right", style="blue", width=14)
    table.add_column(f"Diff ({currency})", justify="right", width=14)
    table.add_column("Diff %", justify="right", width=10)

    for r in below:
        diff_str = f"[red]{r['diff']:+.2f}[/red]"
        pct_str = f"[red]{r['diff_pct']:+.2f}%[/red]"
        price_str = f"{r['price']:.2f}"
        ma_str = f"{r['ma200']:.2f}"
        table.add_row(r["ticker"], r["name"][:28], price_str, ma_str, diff_str, pct_str)

    return table


def main():
    console.print(
        Panel.fit(
            "[bold cyan]📊 Stock Price vs 200-Day Moving Average[/bold cyan]\n"
            "[dim]S&P 100 & Taiwan 50 — Stocks trading BELOW 200MA[/dim]",
            border_style="cyan",
        )
    )
    console.print(
        f"[dim]Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]\n"
    )

    # Fetch data
    sp100_data = fetch_all(SP100_TICKERS, "S&P 100")
    tw50_data = fetch_all(TW50_TICKERS, "Taiwan 50")

    # Display S&P 100
    console.print()
    sp100_table = build_table(sp100_data, "S&P 100 — Below 200MA", currency="USD")
    console.print(sp100_table)

    # Display Taiwan 50
    console.print()
    tw50_table = build_table(tw50_data, "Taiwan 50 — Below 200MA", currency="TWD")
    console.print(tw50_table)

    # Summary
    sp100_below = sum(1 for r in sp100_data if r["below_ma200"])
    tw50_below = sum(1 for r in tw50_data if r["below_ma200"])

    console.print()
    console.print(
        Panel(
            f"[bold]Summary[/bold]\n\n"
            f"[cyan]S&P 100:[/cyan]  {sp100_below:>3} / {len(sp100_data)} stocks below 200MA  "
            f"([red]{sp100_below / len(sp100_data) * 100:.1f}%[/red])\n"
            f"[cyan]Taiwan 50:[/cyan] {tw50_below:>3} / {len(tw50_data)} stocks below 200MA  "
            f"([red]{tw50_below / len(tw50_data) * 100:.1f}%[/red])",
            border_style="green",
            title="[bold green]📋 Final Summary[/bold green]",
        )
    )


if __name__ == "__main__":
    main()
