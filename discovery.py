"""
Discovery agent: finds candidate Solana memecoins via DexScreener's free,
no-key API (token-profiles + token-boosts = "recently promoted/trending").

Docs: https://docs.dexscreener.com/api/reference
"""

import requests

from config import DEXSCREENER_TOKEN_BOOSTS_URL, DEXSCREENER_TOKEN_PROFILES_URL, DEXSCREENER_PAIRS_URL


def discover_trending_solana_tokens(limit: int = 15) -> list[dict]:
    """
    Returns a de-duplicated list of {mint, symbol, name} for tokens on Solana
    that DexScreener currently flags as trending/boosted or newly profiled.
    """
    candidates = {}

    for url in (DEXSCREENER_TOKEN_BOOSTS_URL, DEXSCREENER_TOKEN_PROFILES_URL):
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue

        items = data if isinstance(data, list) else data.get("pairs", [])
        for item in items:
            if item.get("chainId") != "solana":
                continue
            mint = item.get("tokenAddress")
            if not mint or mint in candidates:
                continue
            candidates[mint] = {
                "mint": mint,
                "symbol": item.get("symbol", ""),
                "name": item.get("description", "")[:60],
            }
            if len(candidates) >= limit:
                break

    return list(candidates.values())


def enrich_token_symbol(mint: str) -> dict:
    """Look up symbol/name/price for a specific mint via DexScreener pairs endpoint."""
    try:
        resp = requests.get(f"{DEXSCREENER_PAIRS_URL}/{mint}", timeout=20)
        resp.raise_for_status()
        pairs = resp.json().get("pairs") or []
        if pairs:
            base = pairs[0].get("baseToken", {})
            return {"symbol": base.get("symbol", ""), "name": base.get("name", "")}
    except (requests.RequestException, ValueError):
        pass
    return {"symbol": "", "name": ""}
