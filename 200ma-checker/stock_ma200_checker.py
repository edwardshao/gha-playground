import argparse
import sqlite3
import warnings
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

warnings.filterwarnings("ignore")

console = Console()

# ── SQLite Cache 設定 ─────────────────────────────────────────────────────────
# cache.db 放在與 .py 同一目錄下
DB_PATH = Path(__file__).parent / "cache.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_name (
            stock_id TEXT PRIMARY KEY,
            name     TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS closes (
            stock_id  TEXT    NOT NULL,
            date_key  TEXT    NOT NULL,
            close     REAL    NOT NULL,
            PRIMARY KEY (stock_id, date_key)
        )
    """)
    conn.commit()
    return conn


def load_cache(stock_id: str) -> tuple[dict[str, float], str]:
    """從 SQLite cache 讀取收盤價資料，回傳 (closes dict, name)。"""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT name FROM stock_name WHERE stock_id = ?", (stock_id,)
            ).fetchone()
            name = row[0] if row else stock_id

            rows = conn.execute(
                "SELECT date_key, close FROM closes WHERE stock_id = ?", (stock_id,)
            ).fetchall()
            closes = {r[0]: r[1] for r in rows}
            return closes, name
    except Exception:
        return {}, stock_id


def save_cache(stock_id: str, closes: dict[str, float], name: str) -> None:
    """將收盤價資料寫入 SQLite cache（upsert）。"""
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stock_name (stock_id, name) VALUES (?, ?)",
                (stock_id, name),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO closes (stock_id, date_key, close) VALUES (?, ?, ?)",
                [(stock_id, dk, v) for dk, v in closes.items()],
            )
            conn.commit()
    except Exception:
        pass


TWSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.twse.com.tw/",
    "Accept": "application/json, text/plain, */*",
}


def _twse_date_to_ym(twse_date: str) -> tuple[int, int]:
    """將民國日期字串 '113/12/02' 轉換為西元 (year, month)。"""
    parts = twse_date.split("/")
    year = int(parts[0]) + 1911
    month = int(parts[1])
    return year, month


def get_twse_history(stock_id: str) -> tuple[pd.Series | None, str]:
    """
    從 TWSE 取得收盤價，並使用 local cache 加速。
    - 首次執行：下載全部 15 個月資料並存入 cache
    - 之後執行：只下載 cache 最後一筆之後的月份，合併後更新 cache
    回傳 (Series of close prices, Chinese company name)
    """
    import time

    import requests as _req
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 1. 讀取 cache
    closes, tw_name = load_cache(stock_id)
    today = date.today()

    # 2. 決定要補抓哪些月份
    if closes:
        # 找出 cache 最後一筆的年月，從該月開始重新抓（補足當月可能的新交易日）
        last_twse_date = max(closes.keys())
        last_year, last_month = _twse_date_to_ym(last_twse_date)
        # 計算需要補抓的月份：從 last_month 到現在
        fetch_months: list[tuple[int, int]] = []
        y, m = last_year, last_month
        while (y, m) <= (today.year, today.month):
            fetch_months.append((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1
    else:
        # Cache 不存在，下載全部 15 個月
        fetch_months = []
        for months_back in range(15, -1, -1):
            y = today.year
            m = today.month - months_back
            while m <= 0:
                m += 12
                y -= 1
            fetch_months.append((y, m))

    # 3. 逐月抓取
    newly_fetched = 0
    for y, m in fetch_months:
        date_str = f"{y}{m:02d}01"
        url = (
            f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
            f"?response=json&date={date_str}&stockNo={stock_id}"
        )
        try:
            resp = _req.get(url, headers=TWSE_HEADERS, timeout=10, verify=False)
            data = resp.json()
            if data.get("stat") == "OK":
                # 解析中文名稱
                if tw_name == stock_id and "title" in data:
                    parts = data["title"].split()
                    try:
                        code_idx = next(i for i, p in enumerate(parts) if p == stock_id)
                        name_parts = []
                        for p in parts[code_idx + 1 :]:
                            if "各日" in p or "月" in p:
                                break
                            name_parts.append(p)
                        if name_parts:
                            tw_name = "".join(name_parts)
                    except StopIteration:
                        pass

                for row in data.get("data", []):
                    date_key = row[0].strip()
                    price_str = row[6].replace(",", "").strip()
                    try:
                        closes[date_key] = float(price_str)
                        newly_fetched += 1
                    except ValueError:
                        pass
            time.sleep(0.25)
        except Exception:
            pass

    if len(closes) < 50:
        return None, tw_name

    # 4. 更新 cache（只在有新資料時寫入）
    if newly_fetched > 0:
        save_cache(stock_id, closes, tw_name)

    series = pd.Series(closes).sort_index()
    return series, tw_name


def get_yf_history(ticker: str) -> tuple[pd.Series | None, str]:
    """
    從 yfinance 取得收盤價，並使用 SQLite cache 加速。
    - 首次執行：下載 2 年資料存入 cache
    - 之後執行：只下載 cache 最後一筆日期之後的資料，合併後更新 cache
    回傳 (Series of close prices, name)
    """
    # 1. 讀取 cache（yfinance 用 ISO 日期格式 YYYY-MM-DD 作為 date_key）
    closes, name = load_cache(ticker)

    if closes:
        last_date = max(closes.keys())  # e.g. "2025-03-07"
        # 只補抓 last_date 之後的資料
        stock = yf.Ticker(ticker)
        hist = stock.history(start=last_date, auto_adjust=False)
        newly_fetched = 0
        if not hist.empty:
            # 取名稱
            if name == ticker:
                try:
                    name = stock.info.get("shortName", ticker)
                except Exception:
                    pass
            for dt, row in hist.iterrows():
                dk = str(dt.date())
                if dk not in closes:
                    closes[dk] = float(row["Close"])
                    newly_fetched += 1
            if newly_fetched > 0:
                save_cache(ticker, closes, name)
    else:
        # 首次：下載 2 年完整資料
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y", auto_adjust=False)
        if hist.empty or len(hist) < 50:
            return None, ticker
        try:
            name = stock.info.get("shortName", ticker)
        except Exception:
            name = ticker
        closes = {str(dt.date()): float(row["Close"]) for dt, row in hist.iterrows()}
        save_cache(ticker, closes, name)

    if len(closes) < 50:
        return None, name

    series = pd.Series(closes).sort_index()
    return series, name


def get_stock_data(ticker: str, ma_window: int = 200) -> dict | None:
    """Fetch stock history and compute moving average.

    Both TW and US stocks use SQLite cache; only missing data is fetched.
    """
    try:
        is_tw = ticker.endswith(".TW")

        if is_tw:
            stock_id = ticker.replace(".TW", "")
            close, name = get_twse_history(stock_id)
            if close is None or len(close) < 50:
                console.print(f"[yellow]⚠ 跳過 {ticker}：無法從 TWSE 取得資料[/yellow]")
                return None
            current_price = close.iloc[-1]
        else:
            close, name = get_yf_history(ticker)
            if close is None or len(close) < 50:
                console.print(
                    f"[yellow]⚠ 跳過 {ticker}：無法從 yfinance 取得資料[/yellow]"
                )
                return None
            current_price = close.iloc[-1]

        ma_val = close.rolling(window=ma_window).mean().iloc[-1]

        # Fallback: if not enough history, use available mean
        if pd.isna(ma_val):
            ma_val = close.mean()

        diff = current_price - ma_val
        diff_pct = (diff / ma_val) * 100

        return {
            "ticker": ticker,
            "name": name,
            "price": current_price,
            "ma": ma_val,
            "ma_window": ma_window,
            "diff": diff,
            "diff_pct": diff_pct,
            "below_ma": current_price < ma_val,
        }
    except Exception:
        return None


def fetch_all(tickers: list[str], label: str, ma_window: int) -> list[dict]:
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(tickers)
    results: list[dict] = []
    done = [0]  # mutable counter for use inside nested function
    counter_lock = threading.Lock()

    # TWSE has rate limits — cap at 3 workers; yfinance can handle more
    is_tw = any(t.endswith(".TW") for t in tickers)
    max_workers = 3 if is_tw else 10

    with console.status("") as status:

        def _fetch(ticker: str) -> dict | None:
            return get_stock_data(ticker, ma_window=ma_window)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_fetch, t): t for t in tickers}
            for future in as_completed(futures):
                with counter_lock:
                    done[0] += 1
                    status.update(
                        f"[cyan]Fetching {label} ({ma_window}MA): "
                        f"{done[0]}/{total}[/cyan]"
                    )
                data = future.result()
                if data:
                    results.append(data)

    return results


def build_table(
    results: list[dict],
    title: str,
    currency: str = "USD",
    ma_window: int = 200,
) -> Table:
    below = [r for r in results if r["below_ma"]]
    below.sort(key=lambda x: x["diff_pct"])  # worst performers first

    ma_label = f"{ma_window}MA"

    table = Table(
        title=(
            f"[bold red]📉 {title}[/bold red]\n"
            f"[dim]{len(below)} / {len(results)} stocks below {ma_label}[/dim]"
        ),
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white on dark_blue",
        border_style="blue",
        expand=False,
    )

    table.add_column("Ticker", style="cyan bold", width=12)
    table.add_column("Company", style="white", width=28)
    table.add_column(f"Price ({currency})", justify="right", style="yellow", width=14)
    table.add_column(
        f"{ma_label} ({currency})", justify="right", style="blue", width=14
    )
    table.add_column(f"Diff ({currency})", justify="right", width=14)
    table.add_column("Diff %", justify="right", width=10)

    for r in below:
        table.add_row(
            r["ticker"],
            r["name"][:28],
            f"{r['price']:.2f}",
            f"{r['ma']:.2f}",
            f"[red]{r['diff']:+.2f}[/red]",
            f"[red]{r['diff_pct']:+.2f}%[/red]",
        )

    return table


DEFAULT_SP100_FILE = Path(__file__).parent / "sp100.txt"
DEFAULT_TW50_FILE = Path(__file__).parent / "tw50.txt"


def parse_tickers_file(path: Path) -> list[str]:
    """
    從文字檔讀取 ticker 清單。
    - 每行一個 ticker
    - 支援 # 開頭的註解行
    - 忽略空行
    """
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            tickers.append(line)
    return tickers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stock Price vs Moving Average Scanner (S&P 100 / 台灣50)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Default files (same directory as this script):
  S&P 100 : sp100.txt
  台灣50  : tw50.txt

Ticker file format (one ticker per line, # for comments):
  AAPL
  MSFT   # Microsoft
  NVDA
""",
    )
    parser.add_argument(
        "--sp100",
        type=Path,
        default=DEFAULT_SP100_FILE,
        metavar="FILE",
        help="S&P 100 ticker list file (default: sp100.txt)",
    )
    parser.add_argument(
        "--tw50",
        type=Path,
        default=DEFAULT_TW50_FILE,
        metavar="FILE",
        help="台灣50 ticker list file (default: tw50.txt)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 驗證檔案存在
    for path, label in [(args.sp100, "S&P 100"), (args.tw50, "台灣50")]:
        if not path.exists():
            console.print(f"[bold red]❌ 找不到 {label} ticker 檔案: {path}[/bold red]")
            raise SystemExit(1)

    sp100_tickers = parse_tickers_file(args.sp100)
    tw50_tickers = parse_tickers_file(args.tw50)

    console.print(
        Panel.fit(
            "[bold cyan]📊 Stock Price vs Moving Average Scanner[/bold cyan]\n"
            "[yellow]S&P 100[/yellow] → [bold]200MA[/bold]   ·   "
            "[yellow]台灣50[/yellow] → [bold]240MA[/bold]\n"
            "[dim]Displaying only stocks trading BELOW their respective MA[/dim]",
            border_style="cyan",
        )
    )
    console.print(
        f"[dim]Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
    )
    console.print(f"[dim]S&P 100:  {args.sp100} ({len(sp100_tickers)} tickers)[/dim]")
    console.print(f"[dim]台灣50:   {args.tw50} ({len(tw50_tickers)} tickers)[/dim]")
    console.print(f"[dim]Cache:    {DB_PATH}[/dim]\n")

    # ── S&P 100 · 200MA ──────────────────────────────────────────────────────
    console.rule("[yellow]S&P 100  —  200-Day Moving Average[/yellow]")
    sp100_data = fetch_all(sp100_tickers, "S&P 100", ma_window=200)
    console.print()
    console.print(
        build_table(sp100_data, "S&P 100 — Below 200MA", currency="USD", ma_window=200)
    )

    # ── 台灣50 · 240MA ───────────────────────────────────────────────────────
    console.print()
    console.rule("[yellow]台灣50  —  240-Day Moving Average[/yellow]")
    tw50_data = fetch_all(tw50_tickers, "台灣50", ma_window=240)
    console.print()
    console.print(
        build_table(tw50_data, "台灣50 — Below 240MA", currency="TWD", ma_window=240)
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    sp100_below = sum(1 for r in sp100_data if r["below_ma"])
    tw50_below = sum(1 for r in tw50_data if r["below_ma"])
    sp100_total = len(sp100_data)
    tw50_total = len(tw50_data)

    console.print()
    console.print(
        Panel(
            f"[bold]Summary[/bold]\n\n"
            f"[cyan]S&P 100    (200MA):[/cyan]  {sp100_below:>3} / {sp100_total:<4} "
            f"below 200MA  [red]{sp100_below / max(sp100_total, 1) * 100:.1f}%[/red]\n"
            f"[cyan]台灣50 (240MA):[/cyan]  {tw50_below:>3} / {tw50_total:<4} "
            f"below 240MA  [red]{tw50_below / max(tw50_total, 1) * 100:.1f}%[/red]",
            border_style="green",
            title="[bold green]📋 Final Summary[/bold green]",
        )
    )


if __name__ == "__main__":
    main()
