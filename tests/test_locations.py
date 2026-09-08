"""Unit tests for jobagg.locations - location strings taken VERBATIM from
the project database (sqlite jobagg.db, Sep 2026), not invented."""

import pytest

from jobagg.locations import is_uk_viable


class TestUkViable:
    @pytest.mark.parametrize(
        "location",
        [
            "London",
            "London, UK",
            "London, England, United Kingdom",
            "London, United Kingdom",
            "London (GB)",
            "United Kingdom",
            "London & San Francisco",  # multi-location including a UK office
            "Cardiff, London or Remote (UK)",
        ],
    )
    def test_uk_locations_viable(self, location):
        assert is_uk_viable(location) is True

    @pytest.mark.parametrize(
        "location",
        [
            "Paris",
            "Paris, France",
            "New York, NY",
            "San Francisco, CA; New York, NY",
            "Hong Kong",
            "Chennai, India",
            "Remote, Spain",
            "Remote, Poland",
            "Remote, Kenya",
            "Toronto",
            "Singapore",
            "Shanghai",
            "Ebene",
            "Λευκωσία, Nicosia, Cyprus",
        ],
    )
    def test_non_uk_locations_not_viable(self, location):
        assert is_uk_viable(location) is False

    def test_bare_remote_viable(self):
        assert is_uk_viable("Remote") is True

    def test_unknown_location_viable(self):
        assert is_uk_viable(None) is True
        assert is_uk_viable("") is True
        assert is_uk_viable("   ") is True

    def test_ukraine_does_not_match_uk_token(self):
        assert is_uk_viable("Kyiv, Ukraine") is False

    def test_case_insensitive(self):
        assert is_uk_viable("LONDON") is True
        assert is_uk_viable("london, uk") is True
