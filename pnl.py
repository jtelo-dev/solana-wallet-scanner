"""
Realized P&L engine.

For each wallet + token pair, walk the buy/sell events in chronological order
and FIFO-match sells against the oldest open buys to compute realized profit
in SOL. Unmatched (still-open) buys are ignored — we only score profit that's
actually been realized, since an unrealized paper gain isn't "profitable" yet.
"""

from collections import defaultdict, deque


def compute_wallet_pnl(swap_rows: list[dict]) -> list[dict]:
    """
    swap_rows: rows from db.get_swaps_for_token(mint), already sorted by
               wallet, block_time (as the SQL query guarantees).
    Returns a list of dicts ready for db.upsert_wallet_pnl().
    """
    by_wallet = defaultdict(list)
    for row in swap_rows:
        by_wallet[row["wallet"]].append(row)

    results = []

    for wallet, trades in by_wallet.items():
        trades = sorted(trades, key=lambda r: r["block_time"] or 0)
        open_buys = deque()  # each item: [token_amount_remaining, cost_sol_per_token]
        realized_profit = 0.0
        total_bought_sol = 0.0
        total_sold_sol = 0.0
        wins = 0
        matched_sells = 0

        for t in trades:
            token_amount = t["token_amount"] or 0
            sol_amount = t["sol_amount"] or 0
            if token_amount <= 0:
                continue
            price_per_token = sol_amount / token_amount if token_amount else 0

            if t["side"] == "buy":
                open_buys.append([token_amount, price_per_token])
                total_bought_sol += sol_amount

            elif t["side"] == "sell":
                total_sold_sol += sol_amount
                remaining_to_sell = token_amount
                sell_price = price_per_token
                trade_cost = 0.0
                trade_proceeds = 0.0

                while remaining_to_sell > 0 and open_buys:
                    buy_amount, buy_price = open_buys[0]
                    matched = min(buy_amount, remaining_to_sell)

                    trade_cost += matched * buy_price
                    trade_proceeds += matched * sell_price

                    buy_amount -= matched
                    remaining_to_sell -= matched

                    if buy_amount <= 1e-9:
                        open_buys.popleft()
                    else:
                        open_buys[0][0] = buy_amount

                if trade_proceeds > 0:
                    trade_pnl = trade_proceeds - trade_cost
                    realized_profit += trade_pnl
                    matched_sells += 1
                    if trade_pnl > 0:
                        wins += 1

        win_rate = (wins / matched_sells) if matched_sells else 0.0

        results.append(
            {
                "wallet": wallet,
                "token_mint": trades[0]["token_mint"],
                "realized_profit_sol": round(realized_profit, 6),
                "total_bought_sol": round(total_bought_sol, 6),
                "total_sold_sol": round(total_sold_sol, 6),
                "trade_count": len(trades),
                "win_rate": round(win_rate, 4),
            }
        )

    return results
