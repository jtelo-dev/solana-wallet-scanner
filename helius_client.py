"""
Thin wrapper around Helius's Enhanced Transactions API.

Docs: https://docs.helius.dev/solana-apis/enhanced-transactions-api

We pull parsed transactions for a token mint address. Helius already decodes
DEX swaps (Raydium/Pump.fun/Jupiter/Orca/etc.) into a `type: "SWAP"` shape
with `tokenTransfers` and `nativeTransfers`, so we don't have to hand-decode
instruction data ourselves.

NOTE: swap parsing below is heuristic. Multi-hop routed swaps (e.g. through
Jupiter) can involve several intermediate transfers in one transaction; this
takes the transfer(s) that touch the tracked mint and the SOL/wSOL leg of the
same transaction as the trade's price. Good enough for wallet-level P&L
ranking; not meant to be exact tax-grade accounting.
"""

import requests

from config import HELIUS_API_KEY, HELIUS_BASE_URL, SOL_MINT, TX_PAGE_LIMIT

WSOL_MINT = SOL_MINT


class HeliusError(Exception):
    pass


def _require_key():
    if not HELIUS_API_KEY:
        raise HeliusError(
            "HELIUS_API_KEY is not set. Get a free key at https://dashboard.helius.dev "
            "and set it as an environment variable before running."
        )


def get_token_transactions(mint: str, before: str | None = None, limit: int = TX_PAGE_LIMIT):
    """Fetch recent parsed transactions that touched this token mint address."""
    _require_key()
    url = f"{HELIUS_BASE_URL}/addresses/{mint}/transactions"
    params = {"api-key": HELIUS_API_KEY, "limit": limit}
    if before:
        params["before"] = before

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_swaps_for_token(transactions: list[dict], token_mint: str) -> list[dict]:
    """
    Turn Helius enhanced transactions into normalized swap rows:
    {signature, token_mint, wallet, side, token_amount, sol_amount, block_time}
    """
    rows = []

    for tx in transactions:
        if tx.get("type") != "SWAP":
            continue

        signature = tx.get("signature")
        block_time = tx.get("timestamp")
        token_transfers = tx.get("tokenTransfers", []) or []
        native_transfers = tx.get("nativeTransfers", []) or []

        # Isolate the leg(s) that move the tracked token
        token_legs = [t for t in token_transfers if t.get("mint") == token_mint]
        if not token_legs:
            continue

        # Total SOL that moved in this tx (native SOL + wrapped SOL transfers combined)
        sol_moved = sum(t.get("amount", 0) for t in native_transfers)
        wsol_legs = [t for t in token_transfers if t.get("mint") == WSOL_MINT]
        sol_moved += sum(t.get("tokenAmount", 0) for t in wsol_legs)

        for leg in token_legs:
            wallet = leg.get("toUserAccount") if leg.get("toUserAccount") else leg.get("fromUserAccount")
            from_acct = leg.get("fromUserAccount")
            to_acct = leg.get("toUserAccount")
            token_amount = leg.get("tokenAmount", 0)

            # Heuristic: token flowing INTO a wallet from a pool/program = buy.
            # Token flowing OUT of a wallet into a pool/program = sell.
            # We treat the receiving account as the trader on a buy, and the
            # sending account as the trader on a sell.
            if to_acct:
                side = "buy"
                wallet = to_acct
            elif from_acct:
                side = "sell"
                wallet = from_acct
            else:
                continue

            if not wallet or token_amount == 0:
                continue

            rows.append(
                {
                    "signature": signature,
                    "token_mint": token_mint,
                    "wallet": wallet,
                    "side": side,
                    "token_amount": abs(token_amount),
                    "sol_amount": abs(sol_moved) if sol_moved else 0.0,
                    "block_time": block_time,
                }
            )

    return rows
