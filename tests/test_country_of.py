"""Country derivation from region + Yahoo suffix, and the coarse region groups."""
from equity_scout.universe import REGION_GROUPS, country_of


def test_country_regions_pass_through():
    assert country_of("US", "AAPL") == "US"
    assert country_of("CA", "RY.TO") == "CA"
    assert country_of("JP", "7203.T") == "JP"
    assert country_of("HK", "0700.HK") == "HK"


def test_eu_resolves_via_suffix():
    assert country_of("EU", "MC.PA") == "FR"
    assert country_of("EU", "SAP.DE") == "DE"
    assert country_of("EU", "SHEL.L") == "GB"
    assert country_of("EU", "ASML.AS") == "NL"
    assert country_of("EU", "NESN.SW") == "CH"


def test_uk_region_is_gb():
    assert country_of("UK", "HSBA.L") == "GB"


def test_eu_unknown_or_missing_suffix_falls_back_to_eu():
    assert country_of("EU", "XXX.ZZ") == "EU"
    assert country_of("EU", "NOSUFFIX") == "EU"


def test_region_groups_cover_universe_regions_exactly_once():
    assert set(REGION_GROUPS) == {"europe", "americas", "asia", "oceania"}
    universe_regions = {"US", "EU", "UK", "JP", "HK", "CN", "KR", "IN", "CA", "AU", "BR"}
    for region in universe_regions:
        assert sum(region in codes for codes in REGION_GROUPS.values()) == 1
