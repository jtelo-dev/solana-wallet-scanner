"""
Scanner agent: for one tracked token, pull recent swap transactions from
Solana (via Helius RPC), store the normalized swap rows, then recompute
wallet P&L for that token. Designed to be called per-token from the
dashboard's "Scan now" button, or looped over all tracked tokens on a
schedule.
"""

from config import TX_PAGE_LIMIT
import db
import helius_client
import pnl

# How many getTransaction calls go in a single JSON-RPC batch request.
BATCH_SIZE = 50


def scan_token(mint: str, max_pages: int = 3) -> dict:
    """
    Pulls up to max_pages * TX_PAGE_LIMIT recent signatures for `mint`,
    fetches full transactions in batches, extracts swap rows by balance
    diffing, stores them, recomputes P&L. Returns a small summary dict.
    """
    all_rows = []
    failed_txs = 0
    before = None

    for _ in range(max_pages):
        sig_entries = helius_client.get_signatures_for_mint(mint, before=before, limit=TX_PAGE_LIMIT)
        if not sig_entries:
            break

        # Skip signatures for transactions that failed on-chain (nothing to score).
        signatures = [e["signature"] for e in sig_entries if not e.get("err")]

        for i in range(0, len(signatures), BATCH_SIZE):
            batch = signatures[i : i + BATCH_SIZE]
            tx_map = helius_client.get_transactions_batch(batch)
            for sig in batch:
                tx = tx_map.get(sig)
                if tx is None:
                    failed_txs += 1
                    continue
                all_rows.extend(helius_client.extract_swap_rows(tx, mint))

        if len(sig_entries) < TX_PAGE_LIMIT:
            break
        before = sig_entries[-1].get("signature")

    db.insert_swaps(all_rows)
    db.mark_scanned(mint)

    swap_rows = db.get_swaps_for_token(mint)
    pnl_rows = pnl.compute_wallet_pnl([dict(r) for r in swap_rows])
    db.upsert_wallet_pnl(pnl_rows)

    return {
        "mint": mint,
        "swaps_fetched": len(all_rows),
        "wallets_scored": len(pnl_rows),
        "tx_fetch_failures": failed_txs,
    }


def scan_all_tokens(max_pages: int = 3) -> list[dict]:
    summaries = []
    for token in db.list_tokens():
        try:
            summaries.append(scan_token(token["mint"], max_pages=max_pages))
        except helius_client.HeliusError as e:
            summaries.append({"mint": token["mint"], "error": str(e)})
        except Exception as e:  # noqa: BLE001 - surface it in the UI instead of crashing the app
            summaries.append({"mint": token["mint"], "error": f"Unexpected error: {e}"})
    return summaries
