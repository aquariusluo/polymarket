from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import sqlite3

from dashboard.api.database import get_db

router = APIRouter(prefix='/api')


@router.get('/portfolio')
def get_portfolio(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute('SELECT * FROM positions ORDER BY updated_at DESC').fetchall()
    positions = []
    for r in rows:
        d = dict(r)
        positions.append({
            'condition_id': d.get('condition_id'),
            'asset_id': d.get('asset_id'),
            'market_slug': d.get('market_slug'),
            'side': d.get('side'),
            'shares': d.get('shares'),
            'avg_cost': d.get('avg_cost'),
            'cost_basis': d.get('cost_basis'),
            'updated_at': d.get('updated_at'),
        })
    return positions


@router.get('/portfolio/snapshots')
def get_snapshots(conn: sqlite3.Connection = Depends(get_db), limit: int = Query(200, le=500)):
    rows = conn.execute(
        'SELECT captured_at, total_equity, total_cost_basis, total_market_value, '
        'total_unrealized_pnl, total_realized_pnl, drawdown_pct '
        'FROM portfolio_snapshots ORDER BY id ASC LIMIT ?',
        (limit,),
    ).fetchall()
    snapshots = []
    for r in rows:
        d = dict(r)
        snapshots.append({
            'captured_at': d.get('captured_at'),
            'total_equity': d.get('total_equity'),
            'total_cost_basis': d.get('total_cost_basis'),
            'total_market_value': d.get('total_market_value'),
            'total_unrealized_pnl': d.get('total_unrealized_pnl'),
            'total_realized_pnl': d.get('total_realized_pnl'),
            'drawdown_pct': d.get('drawdown_pct'),
        })
    return snapshots
