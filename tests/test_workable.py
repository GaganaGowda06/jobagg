"""Unit tests for the Workable client. Fixture shapes copied from live
probes of apply.workable.com (g-mass account, Sep 2026)."""

from unittest.mock import MagicMock, patch

import requests

from jobagg.sources.workable import _build_description, _normalize_job, fetch_batch, fetch_jobs

LISTING = {
    "name": "G MASS",
    "jobs": [
        {
            "title": "Graduate Data Scientist",
            "shortcode": "AAA111",
            "employment_type": "Full-time",
            "city": "London",
            "country": "United Kingdom",
            "url": "https://apply.workable.com/j/AAA111",
            "published_on": "2026-08-01",
        },
        {
            "title": "Access Governance & Compliance Operations Consultant",
            "shortcode": "9214B374C4",
            "employment_type": "Contract",
            "city": "New York",
            "country": "United States",
            "url": "https://apply.workable.com/j/9214B374C4",
            "published_on": "2026-06-30",
        },
        {
            "title": "Senior Data Engineer",
            "shortcode": "BBB222",
            "employment_type": "Full-time",
            "city": "London",
            "country": "United Kingdom",
            "url": "https://apply.workable.com/j/BBB222",
            "published_on": "2026-07-15",
        },
    ],
}

DETAILS = {
    "shortcode": "AAA111",
    "title": "Graduate Data Scientist",
    "remote": False,
    "description": "<p>Join our team &amp; build models.</p>",
    "requirements": "<ul><li>Python</li><li>No experience needed</li></ul>",
    "location": {"country": "United Kingdom", "city": "London"},
}


def _response(payload, status=200):
    r = MagicMock()
    r.json.return_value = payload
    if status >= 400:
        r.raise_for_status.side_effect = requests.exceptions.HTTPError()
    return r


class TestBuildDescription:
    def test_strips_html_and_concatenates_requirements(self):
        out = _build_description(DETAILS)
        assert "Join our team & build models." in out
        assert "Requirements:" in out and "No experience needed" in out
        assert "<p>" not in out and "&amp;" not in out

    def test_missing_requirements_ok(self):
        out = _build_description({"description": "<p>Role.</p>"})
        assert out == "Role."
        assert _build_description({}) is None


class TestNormalize:
    def test_common_shape(self):
        job = _normalize_job(LISTING["jobs"][0], DETAILS, "G MASS")
        assert job["source"] == "workable"
        assert job["id"] == "AAA111"
        assert job["company"] == "G MASS"
        assert job["location"] == "London, United Kingdom"
        assert job["created"] == "2026-08-01"
        assert "No experience needed" in job["description"]

    def test_remote_fallback_location(self):
        listing = {"title": "X", "shortcode": "C"}
        assert _normalize_job(listing, {"remote": True}, "Co")["location"] == "Remote"
        assert _normalize_job(listing, {"remote": False}, "Co")["location"] is None


class TestFetchJobs:
    def test_filters_titles_before_details_calls(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            if "widget" in url:
                return _response(LISTING)
            return _response(DETAILS)

        with patch("jobagg.sources.workable._session.get", side_effect=fake_get):
            jobs = fetch_jobs("g-mass")

        details_calls = [c for c in calls if "widget" not in c]
        # 3 listed jobs: Consultant fails relevance, Senior excluded ->
        # only the Graduate job may cost a details request.
        assert len(details_calls) == 1 and "AAA111" in details_calls[0]
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Graduate Data Scientist"
        assert jobs[0]["company"] == "G MASS"

    def test_details_failure_skips_job_only(self):
        def fake_get(url, **kw):
            if "widget" in url:
                return _response(LISTING)
            return _response({}, status=404)

        with patch("jobagg.sources.workable._session.get", side_effect=fake_get):
            jobs = fetch_jobs("g-mass")
        assert jobs == []


class TestFetchBatch:
    def test_company_failure_skips_company(self):
        def fake_get(url, **kw):
            if "broken" in url:
                raise requests.exceptions.ConnectionError()
            if "widget" in url:
                return _response(LISTING)
            return _response(DETAILS)

        with patch("jobagg.sources.workable._session.get", side_effect=fake_get):
            jobs = fetch_batch(["broken-co", "g-mass"])
        assert len(jobs) == 1
