"""
Scanner agent: for one tracked token, pull recent swap transactions from
Helius, store the normalized swap rows, then recompute wallet P&L for that
token. Designed to be called per-token from the dashboard's "Scan now"
button, or looped over all tracked tokens on a schedule.
"""

from config import TX_PAGE_LIMIT
import db
import helius_client
import pnl


def scan_token(mint: str, max_pages: int = 3) -> dict:
    """
    Pulls up to max_pages * TX_PAGE_LIMIT recent transactions for `mint`,
    stores parsed swaps, recomputes P&L. Returns a small summary dict.
    """
    all_rows = []
    before = None

    for _ in range(max_pages):
        txs = helius_client.get_token_transactions(mint, before=before, limit=TX_PAGE_LIMIT)
        if not txs:
            break

        rows = helius_client.parse_swaps_for_token(txs, mint)
        all_rows.extend(rows)

        if len(txs) < TX_PAGE_LIMIT:
            break
        before = txs[-1].get("signature")

    db.insert_swaps(all_rows)
    db.mark_scanned(mint)

    swap_rows = db.get_swaps_for_token(mint)
    pnl_rows = pnl.compute_wallet_pnl([dict(r) for r in swap_rows])
    db.upsert_wallet_pnl(pnl_rows)

    return {
        "mint": mint,
        "swaps_fetched": len(all_rows),
        "wallets_scored": len(pnl_rows),
    }


def scan_all_tokens(max_pages: int = 3) -> list[dict]:
    summaries = []
    for token in db.list_tokens():
        try:
            summaries.append(scan_token(token["mint"], max_pages=max_pages))
        except helius_client.HeliusError as e:
            summaries.append({"mint": token["mint"], "error": str(e)})
    return summaries
