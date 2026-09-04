"""
Configuration for the Solana wallet scanner.
Reads secrets from environment variables (local runs) or Streamlit's secrets
manager (Streamlit Community Cloud) so the Helius key never lives in code.

Setup — running locally:
    1. Get a free Helius API key: https://dashboard.helius.dev (Free tier ~100k credits/month)
    2. Set it as an environment variable before launching Streamlit:
         export HELIUS_API_KEY="your-key-here"      (macOS/Linux)
         setx HELIUS_API_KEY "your-key-here"         (Windows)
    3. Run: streamlit run app.py

Setup — Streamlit Community Cloud:
    Add HELIUS_API_KEY = "your-key-here" under your app's Settings -> Secrets.
    Streamlit exposes it as an environment variable automatically, but this
    file also checks st.secrets directly as a fallback.
"""

import os

try:
    import streamlit as st
    _secrets = st.secrets
except Exception:
    _secrets = {}


def _get_secret(name: str, default: str = "") -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    try:
        return _secrets.get(name, default)  # type: ignore[union-attr]
    except Exception:
        return default


HELIUS_API_KEY = _get_secret("HELIUS_API_KEY")
HELIUS_BASE_URL = "https://api.helius.xyz/v0"
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

DEXSCREENER_TOKEN_PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_TOKEN_BOOSTS_URL = "https://api.dexscreener.com/token-boosts/latest/v1"
DEXSCREENER_PAIRS_URL = "https://api.dexscreener.com/latest/dex/tokens"

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "scanner.db")

# How many transactions to pull per scan pass, per token (Helius paginates by signature)
TX_PAGE_LIMIT = 100

# Minimum realized profit (in SOL) for a wallet to show up as "profitable" in the dashboard
MIN_PROFIT_SOL_THRESHOLD = 0.05

SOL_MINT = "So11111111111111111111111111111111111111112"
