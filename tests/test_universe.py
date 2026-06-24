from pathlib import Path

from equity_scout.universe import load_universe


def test_load_universe_parses_rows(tmp_path: Path):
    csv = tmp_path / "u.csv"
    csv.write_text(
        "ticker,name,exchange,region,currency,sector\n"
        "AAPL,Apple,NASDAQ,US,USD,Technology\n"
        "SAP.DE,SAP,XETRA,EU,EUR,Technology\n"
    )
    universe = load_universe(csv)
    assert len(universe) == 2
    assert universe[1].ticker == "SAP.DE"
    assert universe[1].currency == "EUR"


def test_v1_universe_file_loads():
    universe = load_universe("data/universe_v1.csv")
    assert len(universe) >= 30
    # contains non-US tickers with Yahoo suffixes
    assert any("." in inst.ticker for inst in universe)
