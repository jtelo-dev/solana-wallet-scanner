"""
Streamlit dashboard: Solana memecoin profitable-wallet scanner.

Run with:
    export HELIUS_API_KEY="your-key"
    streamlit run app.py
"""

import pandas as pd
import streamlit as st

import config
import db
import discovery
import scanner

st.set_page_config(page_title="Solana Wallet Scanner", layout="wide")
db.init_db()

st.title("🔍 Solana Memecoin — Profitable Wallet Scanner")
st.caption(
    "Tracks a set of memecoins, pulls swap history via Helius, and ranks wallets "
    "by realized (FIFO) profit in SOL."
)

if not config.HELIUS_API_KEY:
    st.warning(
        "No `HELIUS_API_KEY` found. Get a free key at "
        "[dashboard.helius.dev](https://dashboard.helius.dev) and set it as an "
        "environment variable, then restart this app."
    )

# ---------------------------------------------------------------- Sidebar
with st.sidebar:
    st.header("Tracked tokens")

    with st.form("add_token_form", clear_on_submit=True):
        new_mint = st.text_input("Add token by mint address")
        submitted = st.form_submit_button("Add")
        if submitted and new_mint.strip():
            meta = discovery.enrich_token_symbol(new_mint.strip())
            db.add_token(new_mint.strip(), meta.get("symbol", ""), meta.get("name", ""), source="manual")
            st.success(f"Added {meta.get('symbol') or new_mint[:6]}")
            st.rerun()

    if st.button("🔎 Discover trending Solana memecoins"):
        found = discovery.discover_trending_solana_tokens(limit=15)
        for t in found:
            db.add_token(t["mint"], t["symbol"], t["name"], source="discovered")
        st.success(f"Added {len(found)} discovered tokens (duplicates skipped).")
        st.rerun()

    st.divider()

    tokens = db.list_tokens()
    if not tokens:
        st.info("No tokens tracked yet. Add one above or run discovery.")
    else:
        for t in tokens:
            label = t["symbol"] or t["mint"][:8]
            scanned = t["last_scanned_at"] or "never"
            st.write(f"**{label}** · `{t['mint'][:6]}…{t['mint'][-4:]}`")
            st.caption(f"source: {t['source']} · last scanned: {scanned}")

    st.divider()
    min_profit = st.number_input(
        "Min realized profit to show (SOL)",
        min_value=0.0,
        value=config.MIN_PROFIT_SOL_THRESHOLD,
        step=0.05,
    )

# ---------------------------------------------------------------- Main
col1, col2 = st.columns([1, 3])
with col1:
    scan_clicked = st.button("▶️ Scan all tracked tokens now", type="primary", use_container_width=True)

if scan_clicked:
    if not tokens:
        st.warning("Add at least one token first.")
    else:
        with st.spinner("Pulling swap history from Helius and computing P&L…"):
            summaries = scanner.scan_all_tokens(max_pages=3)
        for s in summaries:
            if "error" in s:
                st.error(f"{s['mint'][:8]}…: {s['error']}")
            else:
                st.write(f"✅ `{s['mint'][:8]}…` — {s['swaps_fetched']} swaps, {s['wallets_scored']} wallets scored")

st.subheader("🏆 Top profitable wallets (across all tracked tokens)")
rows = db.top_profitable_wallets(min_profit=min_profit, limit=50)

if not rows:
    st.info("No wallet P&L data yet — add tokens and run a scan.")
else:
    df = pd.DataFrame([dict(r) for r in rows])
    df.rename(
        columns={
            "wallet": "Wallet",
            "total_profit_sol": "Realized Profit (SOL)",
            "total_trades": "Trades",
            "tokens_traded": "Tokens Traded",
            "avg_win_rate": "Avg Win Rate",
        },
        inplace=True,
    )
    df["Avg Win Rate"] = (df["Avg Win Rate"] * 100).round(1).astype(str) + "%"
    df["Realized Profit (SOL)"] = df["Realized Profit (SOL)"].round(4)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Wallet drill-down")
    selected_wallet = st.selectbox("Pick a wallet to see its per-token breakdown", df["Wallet"])
    if selected_wallet:
        detail_rows = db.wallet_detail(selected_wallet)
        detail_df = pd.DataFrame([dict(r) for r in detail_rows])
        st.dataframe(detail_df, use_container_width=True, hide_index=True)
