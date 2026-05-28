from app.storage.repositories import LeaderTradeRepository


def test_trade_insert_if_new_deduplicates(db_conn, sample_trade):
    repo = LeaderTradeRepository(db_conn)

    assert repo.insert_if_new(sample_trade) is True
    assert repo.insert_if_new(sample_trade) is False
