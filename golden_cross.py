"""
Stock Screener + Backtester
Pulls data, flags golden cross buy signals, visualizes
the signals, and backtests whether they worked historically
"""

# (Imports)
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import sqlite3


# Step 1: Choose stocks to screen
#-------------------------------------------
tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM"]

# -------------------------------------------
# Step 2: Pull the 2 years of price history
# -------------------------------------------

all_data = {}

for symbol in tickers:
    print(f"Pulling data for {symbol}...")
    stock = yf.Ticker(symbol)
    all_data[symbol] = stock.history(period="2y")

# -------------------------------------------
# STEP 3: Calculate moving averages
# -------------------------------------------
for symbol, df in all_data.items():
    df["MA50"] = df["Close"].rolling(window=50).mean()
    df["MA200"] = df["Close"].rolling(window=200).mean()

# -------------------------------------------
# STEP 4: Flag "golden cross" signals
# (The moment 50-day average crosses ABOVE 200-day average)
# -------------------------------------------
for symbol, df in all_data.items():
    df["above"] = df["MA50"] > df["MA200"]
    df["crossover"] = df["above"] & ~df["above"].shift(1).fillna(False)

# -------------------------------------------
# STEP 5: Print which stocks currently have an active signal
# -------------------------------------------
print("\n--- Current Screener Results ---")
for symbol, df in all_data.items():
    if df["crossover"].iloc[-5:].any():
        print(f"{symbol}: recent golden cross detected")

# -------------------------------------------
# STEP 6: Save results to CSV
# -------------------------------------------
for symbol, df in all_data.items():
    df.to_csv(f"{symbol}_data.csv")

# -------------------------------------------
# STEP 7: Save results to a SQLite database
# -------------------------------------------
conn = sqlite3.connect("stocks.db")
for symbol, df in all_data.items():
    df.to_sql(symbol, conn, if_exists="replace")
conn.close()
print("\nSaved all data to stocks.db")

# -------------------------------------------
# STEP 8: Visualize one stock's price with the moving averages
# -------------------------------------------
symbol_to_plot = "MSFT"
df = all_data[symbol_to_plot]

plt.figure(figsize=(12, 6))
plt.plot(df.index, df["Close"], label="Price", linewidth=1)
plt.plot(df.index, df["MA50"], label="50-day MA", linewidth=1)
plt.plot(df.index, df["MA200"], label="200-day MA", linewidth=1)

# Mark the crossovers on the chart
crossover_points = df[df["crossover"]]
plt.scatter(crossover_points.index, crossover_points["Close"],
            color="green", marker="^", s=100, label="Buy Signal", zorder=5)

plt.title(f"{symbol_to_plot} Price with Golden Cross Signals")
plt.xlabel("Date")
plt.ylabel("Price ($)")
plt.legend()
plt.tight_layout()
plt.show()

# ----------------------------------------------
# STEP 9: Backtest - what happened after each past signal?
# ----------------------------------------------
results = []

for symbol, df in all_data.items():
    crossover_dates = df[df["crossover"]].index
    for date in crossover_dates:
        idx = df.index.get_loc(date)
        if idx+60 < len(df): # need 60 future trading days to measure
            start_price = df["Close"].iloc[idx]
            future_price = df["Close"].iloc[idx+60]
            pct_change = (future_price - start_price) / start_price * 100
            results.append({
                "symbol": symbol,
                "signal_date": date.strftime("%Y-%m-%d"),
                "return_60d_pct": round(pct_change, 2),
            })

results_df = pd.DataFrame(results)

print("\n--- Backtest Results ---")
if not results_df.empty:
    print(results_df)
    print(f"\nAverage 60-day return after signal: {results_df['return_60d_pct'].mean():.2f}%")
    print(f"Number of signals tested: {len(results_df)}")
    print(f"Win rate (positive return): {(results_df['return_60d_pct'] >  0).mean() * 100:.1f}%")
else:
    print("No signals found with enough future data to backtest. Try a longer history period.")