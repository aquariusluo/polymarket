from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import sqlite3

from dashboard.api.database import get_db

router = APIRouter(prefix='/api')


@router.get('/leaders')
def get_leaders(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        'SELECT l.rank, l.wallet, l.name, l.pseudonym, l.pnl_snapshot, l.volume_snapshot, l.selected_at, '
        'COUNT(t.id) AS trade_count, MAX(t.timestamp) AS last_trade_at '
        'FROM leaders l LEFT JOIN leader_trades t ON l.wallet = t.wallet '
        'WHERE l.selection_run_id = (SELECT MAX(selection_run_id) FROM leaders) '
        'GROUP BY l.wallet ORDER BY l.rank'
    ).fetchall()
    leaders = []
    for r in rows:
        d = dict(r)
        leaders.append({
            'rank': d.get('rank'),
            'wallet': d.get('wallet'),
            'name': d.get('name'),
            'pseudonym': d.get('pseudonym'),
            'pnl_snapshot': d.get('pnl_snapshot'),
            'volume_snapshot': d.get('volume_snapshot'),
            'selected_at': d.get('selected_at'),
            'trade_count': d.get('trade_count', 0),
            'last_trade_at': d.get('last_trade_at'),
        })
    return leaders


@router.get('/leaders/{wallet}/trades')
def get_leader_trades(wallet: str, conn: sqlite3.Connection = Depends(get_db), limit: int = Query(20, le=100)):
    rows = conn.execute(
        'SELECT id, transaction_hash, condition_id, asset_id, side, size, price, '
        'timestamp, market_title, market_slug, ingested_at '
        'FROM leader_trades WHERE wallet = ? ORDER BY id DESC LIMIT ?',
        (wallet, limit),
    ).fetchall()
    trades = []
    for r in rows:
        d = dict(r)
        trades.append({
            'id': d.get('id'),
            'transaction_hash': d.get('transaction_hash'),
            'condition_id': d.get('condition_id'),
            'asset_id': d.get('asset_id'),
            'side': d.get('side'),
            'size': d.get('size'),
            'price': d.get('price'),
            'timestamp': d.get('timestamp'),
            'market_title': d.get('market_title'),
            'market_slug': d.get('market_slug'),
            'ingested_at': d.get('ingested_at'),
        })
    return trades
