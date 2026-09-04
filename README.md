# Solana Memecoin — Profitable Wallet Scanner

Local Streamlit dashboard that tracks a set of Solana memecoins (manual list +
auto-discovered trending tokens), pulls their swap history, and ranks wallets
by realized profit (FIFO-matched buys vs. sells, in SOL).

## How it works

1. **Discovery agent** (`discovery.py`) — pulls trending/boosted Solana tokens
   from DexScreener's free, no-key API.
2. **Scanner agent** (`scanner.py`) — for each tracked token, pulls recent
   parsed swap transactions from **Helius** (which already decodes Raydium /
   Pump.fun / Jupiter / Orca swaps for you) and stores normalized buy/sell
   rows in SQLite.
3. **P&L engine** (`pnl.py`) — FIFO-matches each wallet's sells against its
   oldest open buys per token, so profit is *realized* profit, not paper gains.
4. **Dashboard** (`app.py`) — Streamlit UI: add tokens, run scans, see the
   leaderboard of profitable wallets, drill into any wallet's per-token history.

## Setup — Option A: hosted, no terminal (recommended if you just want a link to click)

Streamlit has a free hosting service ("Community Cloud") that runs the app for
you and gives you a URL. You only touch a web browser.

1. Create a free GitHub account at github.com if you don't have one.
2. Create a new repository (e.g. `solana-wallet-scanner`), then use GitHub's
   **"Add file → Upload files"** button on the repo page to drag in all the
   files from this folder (app.py, config.py, db.py, discovery.py,
   helius_client.py, pnl.py, scanner.py, requirements.txt, README.md,
   .gitignore). Commit.
3. Get a free Helius API key at [dashboard.helius.dev](https://dashboard.helius.dev).
4. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, click **"New app"**, pick your repo/branch, and set the main file
   to `app.py`.
5. Before clicking Deploy, open **"Advanced settings" → Secrets** and paste:
   ```
   HELIUS_API_KEY = "your-key-here"
   ```
6. Click **Deploy**. In a minute or two you'll get a public URL
   (`yourname-solana-wallet-scanner.streamlit.app`) — bookmark it and use the
   dashboard from there, same as any website.

Note: the app's SQLite database resets whenever the app restarts/redeploys on
the free tier, since there's no persistent disk. Fine for a scanning tool you
re-run periodically; if you want history to survive restarts, see "Extending
it" below for swapping in a hosted database.

## Setup — Option B: run it yourself locally

```bash
cd solana-wallet-scanner
pip install -r requirements.txt

# Get a free Helius API key: https://dashboard.helius.dev (free tier ≈100k credits/month)
export HELIUS_API_KEY="your-key-here"       # macOS/Linux
# setx HELIUS_API_KEY "your-key-here"       # Windows (new terminal after)

streamlit run app.py
```

## Using it

- **Add a token** by mint address in the sidebar, or click **"Discover
  trending Solana memecoins"** to auto-populate from DexScreener.
- Click **"Scan all tracked tokens now"** — pulls up to ~300 recent
  transactions per token (3 pages × 100), parses swaps, updates wallet P&L.
- The leaderboard shows wallets with realized profit above the threshold
  you set in the sidebar (default 0.05 SOL), ranked highest first.
- Click a wallet in the drill-down box to see its per-token breakdown.

## Known limitations (read before trusting the numbers)

- **Swap parsing is heuristic, not exact.** Multi-hop routed swaps (e.g. via
  Jupiter aggregating across several pools in one transaction) can involve
  several transfers; the parser takes the leg(s) touching the tracked mint
  plus the SOL/wSOL leg of the same transaction as that trade's price. Good
  enough for *ranking* wallets, not for tax-grade accounting.
- **Only realized P&L counts.** A wallet sitting on a huge unrealized gain
  (bought, never sold) won't show up — intentionally, since "profitable"
  here means they've actually cashed out ahead.
- **Helius free tier is credit-limited** (~100k/month). Each scan pass costs
  roughly `tokens_tracked × pages × page_size` in API calls. Scanning fewer
  tokens less often stretches the free tier further.
- **No historical backfill beyond what a scan pulls.** Increase `max_pages`
  in `scanner.py` if you want deeper history per scan (costs more credits).
- Not audited for wash-trading or sybil wallets — a single actor running many
  wallets could look like several "profitable wallets."

## Extending it

- Run `scanner.scan_all_tokens()` on a schedule (cron, `APScheduler`, or a
  loop) instead of only on button click, for a always-fresh leaderboard.
- Swap SQLite for Postgres if you want multiple people hitting the dashboard
  at once.
- Add a "new wallet alert" — diff the leaderboard between scans and flag
  wallets that just crossed your profit threshold.
