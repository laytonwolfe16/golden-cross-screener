"""
Golden Cross Screener + Backtester

Pulls price history, flags golden crosses (50-day MA crossing above the
200-day MA), charts them, and backtests what happened afterward -- compared
against a baseline of "buying on a random day" so the result actually means
something.

Usage:
    python golden_cross.py
    python golden_cross.py --tickers AAPL MSFT NVDA --period 10y --plot NVDA
"""

import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM"]
FAST_WINDOW = 50
SLOW_WINDOW = 200
HORIZONS = (20, 60, 120)  # trading days to look ahead after a signal
OUTPUT_DIR = Path("output")


# ---------------------------------------------------------------- data
def download_prices(tickers, period):
    """Download daily prices; skip tickers that fail or have too little data."""
    data = {}
    for symbol in tickers:
        print(f"Pulling data for {symbol}...")
        try:
            df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
        except Exception as exc:  # network errors, bad tickers, etc.
            print(f"  Skipping {symbol}: {exc}")
            continue
        if df.empty or len(df) <= SLOW_WINDOW:
            print(f"  Skipping {symbol}: not enough data")
            continue
        df.index = df.index.tz_localize(None)  # simpler for CSV/SQLite
        data[symbol] = df
    return data


# ------------------------------------------------------------- signals
def add_signals(df):
    """Add moving averages and flag golden cross days."""
    df = df.copy()
    df["MA_FAST"] = df["Close"].rolling(FAST_WINDOW).mean()
    df["MA_SLOW"] = df["Close"].rolling(SLOW_WINDOW).mean()
    above = df["MA_FAST"] > df["MA_SLOW"]  # False while MAs are still NaN
    df["above"] = above
    df["golden_cross"] = above & ~above.shift(1, fill_value=False)
    return df


# ------------------------------------------------------------ screener
def print_screen(data, lookback=5):
    print("\n--- Current Screener Results ---")
    for symbol, df in data.items():
        recent = df["golden_cross"].iloc[-lookback:].any()
        in_uptrend = bool(df["above"].iloc[-1])
        if recent:
            print(f"{symbol}: NEW golden cross in the last {lookback} days")
        elif in_uptrend:
            print(f"{symbol}: 50-day is above 200-day (no fresh cross)")


# ------------------------------------------------------------ backtest
def backtest(data, horizons=HORIZONS):
    """
    For every golden cross, measure the forward return at each horizon.
    Also compute a baseline: the forward return from ANY day (once the
    200-day MA exists). A signal only "works" if it beats the baseline.
    """
    trades = []
    baseline = {h: [] for h in horizons}

    for symbol, df in data.items():
        fwd = {h: (df["Close"].shift(-h) / df["Close"] - 1) * 100 for h in horizons}
        valid = df["MA_SLOW"].notna()
        for h in horizons:
            baseline[h].append(fwd[h][valid].dropna())

        for date in df.index[df["golden_cross"]]:
            row = {"symbol": symbol, "signal_date": date.strftime("%Y-%m-%d")}
            for h in horizons:
                row[f"ret_{h}d_pct"] = round(fwd[h].loc[date], 2)
            trades.append(row)

    trades_df = pd.DataFrame(trades)

    summary = []
    for h in horizons:
        col = f"ret_{h}d_pct"
        vals = trades_df[col].dropna() if not trades_df.empty else pd.Series(dtype=float)
        base = pd.concat(baseline[h])
        summary.append({
            "horizon_days": h,
            "signals": len(vals),
            "signal_mean_pct": round(vals.mean(), 2),
            "signal_median_pct": round(vals.median(), 2),
            "signal_win_rate_pct": round((vals > 0).mean() * 100, 1),
            "baseline_mean_pct": round(base.mean(), 2),
            "baseline_win_rate_pct": round((base > 0).mean() * 100, 1),
        })
    return trades_df, pd.DataFrame(summary)


# ---------------------------------------------------------------- plot
def plot_stock(df, symbol, show=False):
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df.index, df["Close"], label="Price", linewidth=1)
    ax.plot(df.index, df["MA_FAST"], label=f"{FAST_WINDOW}-day MA", linewidth=1)
    ax.plot(df.index, df["MA_SLOW"], label=f"{SLOW_WINDOW}-day MA", linewidth=1)
    crosses = df[df["golden_cross"]]
    ax.scatter(crosses.index, crosses["Close"], color="green", marker="^",
               s=100, label="Golden cross", zorder=5)
    ax.set_title(f"{symbol} Price with Golden Cross Signals")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price ($)")
    ax.legend()
    fig.tight_layout()
    path = OUTPUT_DIR / f"{symbol}_chart.png"
    fig.savefig(path, dpi=150)
    print(f"Saved chart to {path}")
    if show:
        plt.show()
    plt.close(fig)


# --------------------------------------------------------------- saving
def save_data(data):
    OUTPUT_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(OUTPUT_DIR / "stocks.db") as conn:
        for symbol, df in data.items():
            df.to_csv(OUTPUT_DIR / f"{symbol}_data.csv")
            df.to_sql(symbol, conn, if_exists="replace")
    print(f"\nSaved CSVs and stocks.db to {OUTPUT_DIR}/")


# ----------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="Golden cross screener + backtester")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--period", default="10y", help="e.g. 5y, 10y, max")
    parser.add_argument("--plot", default=None, help="ticker to chart (default: first)")
    parser.add_argument("--show", action="store_true", help="open the chart window")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    raw = download_prices([t.upper() for t in args.tickers], args.period)
    if not raw:
        print("No data downloaded. Check your internet connection and tickers.")
        return
    data = {symbol: add_signals(df) for symbol, df in raw.items()}

    print_screen(data)
    save_data(data)

    plot_symbol = (args.plot or next(iter(data))).upper()
    if plot_symbol in data:
        plot_stock(data[plot_symbol], plot_symbol, show=args.show)

    trades, summary = backtest(data)
    trades.to_csv(OUTPUT_DIR / "backtest_trades.csv", index=False)
    summary.to_csv(OUTPUT_DIR / "backtest_summary.csv", index=False)

    print("\n--- Backtest: every signal ---")
    print(trades.to_string(index=False) if not trades.empty else "No signals found.")
    print("\n--- Backtest summary (signal vs. buying on any day) ---")
    print(summary.to_string(index=False))
    print("\nNote: small sample sizes and a hand-picked list of large, "
          "successful companies (survivorship bias) limit what this proves.")


if __name__ == "__main__":
    main()