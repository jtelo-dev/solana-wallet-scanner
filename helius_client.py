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

import time

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


def _post_rpc(payload: dict, timeout: int = 30, retries: int = 2) -> dict:
    """
    POST a single JSON-RPC request and surface the *real* failure reason
    (status code + response body) instead of a generic HTTPError, so it's
    visible in the Streamlit UI instead of getting redacted. Retries once on
    HTTP 429 (rate limited) with a short backoff.
    """
    last_error = None
    for attempt in range(retries + 1):
        resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=timeout)
        if resp.status_code == 429 and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        if not resp.ok:
            raise HeliusError(
                f"Helius RPC request failed — HTTP {resp.status_code}: {resp.text[:400]}"
            )
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise HeliusError(f"Helius RPC error: {data['error']}")
        return data
    raise HeliusError(f"Helius RPC request failed after retries: {last_error}")


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
    data = _post_rpc(payload)
    return data.get("result", []) or []


def get_transaction(signature: str) -> dict | None:
    """Fetch one full parsed transaction by signature."""
    _require_key()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    }
    data = _post_rpc(payload)
    return data.get("result")


def get_transactions_batch(signatures: list[str]) -> dict:
    """
    Fetch full parsed transactions for a list of signatures. Despite the
    name, this issues individual requests rather than a JSON-RPC batch —
    Helius's shared/free RPC tier rejects batched requests outright, which
    is exactly the error this replaced. Individual calls are slightly slower
    but far more reliable. A single signature's failure doesn't abort the
    rest of the scan; it's just skipped and counted as a failure.
    Returns {signature: parsed_tx_or_None}.
    """
    out = {}
    for sig in signatures:
        try:
            out[sig] = get_transaction(sig)
        except HeliusError:
            out[sig] = None
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
