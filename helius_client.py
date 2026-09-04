"""
Solana RPC client (via Helius's RPC endpoint) for pulling swap activity for a
token mint.

Why not the Enhanced Transactions API (v0/addresses/.../transactions)?
Helius has moved that product to maintenance mode, and by their own docs it
only reliably classifies transactions as `type: "SWAP"` for NFT/Jupiter/SPL
activity. Tokens that trade on their own program before migrating to an AMM
-- e.g. pump.fun bonding-curve trades -- often never get tagged SWAP at all,
so filtering on that field silently returns zero rows for exactly those
tokens.

Instead, this pulls raw transactions and detects trades by diffing each
wallet's token balance and native SOL balance from before -> after the
transaction (pre/postTokenBalances, pre/postBalances). This works regardless
of which program executed the trade, since any wallet that ends up with more
or less of the tracked token, and a corresponding SOL change, was trading it.
"""

import requests

from config import HELIUS_API_KEY, HELIUS_RPC_URL

LAMPORTS_PER_SOL = 1_000_000_000


class HeliusError(Exception):
    pass


def _require_key():
    if not HELIUS_API_KEY:
        raise HeliusError(
            "HELIUS_API_KEY is not set. Get a free key at https://dashboard.helius.dev "
            "and set it as an environment variable (or Streamlit secret)."
        )


def get_signatures_for_mint(mint: str, before: str | None = None, limit: int = 100) -> list[dict]:
    """Recent transaction signatures that touched this token mint address."""
    _require_key()
    params = {"limit": limit}
    if before:
        params["before"] = before

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [mint, params],
    }
    resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise HeliusError(f"RPC error on getSignaturesForAddress: {data['error']}")
    return data.get("result", []) or []


def get_transactions_batch(signatures: list[str]) -> dict:
    """
    Fetch full parsed transactions for a batch of signatures in one HTTP
    round trip (JSON-RPC batch request). Returns {signature: parsed_tx_or_None}.
    """
    _require_key()
    if not signatures:
        return {}

    payload = [
        {
            "jsonrpc": "2.0",
            "id": i,
            "method": "getTransaction",
            "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        }
        for i, sig in enumerate(signatures)
    ]
    resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=60)
    resp.raise_for_status()
    results = resp.json()

    out = {}
    for r in results:
        idx = r.get("id")
        if idx is None or not (0 <= idx < len(signatures)):
            continue
        out[signatures[idx]] = r.get("result") if "error" not in r else None
    return out


def extract_swap_rows(tx: dict, token_mint: str) -> list[dict]:
    """
    Diff a parsed transaction's token + SOL balances to detect trades of
    `token_mint`. Returns normalized rows:
    {signature, token_mint, wallet, side, token_amount, sol_amount, block_time}
    """
    if not tx:
        return []

    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return []  # skip failed transactions

    message = (tx.get("transaction") or {}).get("message") or {}
    account_keys_raw = message.get("accountKeys", [])
    account_keys = [
        k.get("pubkey") if isinstance(k, dict) else k for k in account_keys_raw
    ]
    if not account_keys:
        return []

    fee = meta.get("fee", 0)
    fee_payer = account_keys[0]
    block_time = tx.get("blockTime")
    signatures = (tx.get("transaction") or {}).get("signatures", [])
    signature = signatures[0] if signatures else None

    pre_token = {
        (b["owner"], b["mint"]): (b.get("uiTokenAmount") or {}).get("uiAmount") or 0
        for b in meta.get("preTokenBalances", []) or []
        if b.get("owner")
    }
    post_token = {
        (b["owner"], b["mint"]): (b.get("uiTokenAmount") or {}).get("uiAmount") or 0
        for b in meta.get("postTokenBalances", []) or []
        if b.get("owner")
    }

    pre_balances = meta.get("preBalances", []) or []
    post_balances = meta.get("postBalances", []) or []
    pre_lamports = {account_keys[i]: lam for i, lam in enumerate(pre_balances) if i < len(account_keys)}
    post_lamports = {account_keys[i]: lam for i, lam in enumerate(post_balances) if i < len(account_keys)}

    owners = {o for (o, m) in pre_token if m == token_mint} | {o for (o, m) in post_token if m == token_mint}

    rows = []
    for owner in owners:
        pre_amt = pre_token.get((owner, token_mint), 0)
        post_amt = post_token.get((owner, token_mint), 0)
        token_delta = post_amt - pre_amt

        if abs(token_delta) < 1e-9:
            continue

        pre_lam = pre_lamports.get(owner)
        post_lam = post_lamports.get(owner)
        if pre_lam is None or post_lam is None:
            continue

        lamports_delta = post_lam - pre_lam
        if owner == fee_payer:
            lamports_delta += fee  # exclude the tx fee from the trade's cost/proceeds

        sol_amount = abs(lamports_delta) / LAMPORTS_PER_SOL
        if sol_amount == 0:
            continue  # a SOL-side change is required to call this a trade, not a transfer

        side = "buy" if token_delta > 0 else "sell"

        rows.append(
            {
                "signature": signature,
                "token_mint": token_mint,
                "wallet": owner,
                "side": side,
                "token_amount": abs(token_delta),
                "sol_amount": sol_amount,
                "block_time": block_time,
            }
        )

    return rows
