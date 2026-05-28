from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import sqlite3

from dashboard.api.database import get_db

router = APIRouter(prefix='/api')


@router.get('/signals')
def get_signals(conn: sqlite3.Connection = Depends(get_db), limit: int = Query(50, le=200), offset: int = 0):
    rows = conn.execute(
        'SELECT s.id, s.wallet, s.leader_name, s.condition_id, s.market_slug, s.side, '
        's.leader_price, s.decision, s.reason, s.detected_at, '
        'o.status AS order_status, o.reason AS order_reason '
        'FROM signals s LEFT JOIN sim_orders o ON s.id = o.signal_id '
        'ORDER BY s.id DESC LIMIT ? OFFSET ?',
        (limit, offset),
    ).fetchall()
    signals = []
    for r in rows:
        d = dict(r)
        signals.append({
            'id': d.get('id'),
            'wallet': d.get('wallet'),
            'leader_name': d.get('leader_name'),
            'condition_id': d.get('condition_id'),
            'market_slug': d.get('market_slug'),
            'side': d.get('side'),
            'leader_price': d.get('leader_price'),
            'decision': d.get('decision'),
            'reason': d.get('reason'),
            'detected_at': d.get('detected_at'),
            'order_status': d.get('order_status'),
            'order_reason': d.get('order_reason'),
        })
    return signals


@router.get('/signals/funnel')
def get_funnel(conn: sqlite3.Connection = Depends(get_db)):
    total_trades = conn.execute('SELECT COUNT(*) FROM leader_trades').fetchone()[0]

    accepted = conn.execute("SELECT COUNT(*) FROM signals WHERE decision = 'accepted'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM signals WHERE decision = 'rejected'").fetchone()[0]

    filled = conn.execute("SELECT COUNT(*) FROM sim_orders WHERE status = 'filled'").fetchone()[0]
    order_rejected = conn.execute("SELECT COUNT(*) FROM sim_orders WHERE status = 'rejected'").fetchone()[0]

    pending = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE decision = 'accepted' "
        "AND id NOT IN (SELECT signal_id FROM sim_orders)"
    ).fetchone()[0]

    return {
        'total_trades': total_trades,
        'accepted_signals': accepted,
        'rejected_signals': rejected,
        'filled_orders': filled,
        'rejected_orders': order_rejected,
        'pending_signals': pending,
    }
