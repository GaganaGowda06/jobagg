"""Tests for jobagg.sources.greenhouse."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest
import requests
from requests.adapters import HTTPAdapter

from jobagg.filtering import (
    DEFAULT_FALSE_POSITIVE_PHRASES,
    DEFAULT_INCLUDE_WORDS,
    _title_relevant,
)
from jobagg.sources.greenhouse import (
    _clean_html,
    _normalize_job,
    _retry,
    _session,
    fetch_batch,
    fetch_jobs,
)

# Same gotcha as Adzuna/Reed's tests: the retry adapter in greenhouse.py is
# only mounted for https:// (matching the real Greenhouse API). The local
# test server below is plain http://, so the same retry policy is mounted
# here too.
_session.mount("http://", HTTPAdapter(max_retries=_retry))


class TestCleanHtml:
    def test_unescapes_and_strips_tags(self):
        raw = "&lt;p&gt;&lt;strong&gt;Hello&lt;/strong&gt; world&lt;/p&gt;"
        assert _clean_html(raw) == "Hello world"

    def test_collapses_whitespace_from_stripped_tags(self):
        raw = "&lt;div&gt;A&lt;/div&gt;&lt;div&gt;B&lt;/div&gt;"
        result = _clean_html(raw)
        assert result == "A B"

    def test_handles_none(self):
        assert _clean_html(None) is None

    def test_handles_empty_string(self):
        assert _clean_html("") is None


class TestNormalizeJob:
    def test_normalizes_real_job(self):
        # Actual Greenhouse API response for Monzo's "Anaplan Support
        # Analyst" listing, verified against the live API during ATS ingest.
        raw = {
            "absolute_url": "https://job-boards.greenhouse.io/monzo/jobs/8143930",
            "id": 8143930,
            "location": {"name": "Cardiff, London or Remote (UK)"},
            "title": "Anaplan Support Analyst",
            "company_name": "Monzo",
            "first_published": "2026-08-24T09:04:42-04:00",
            "content": (
                "&lt;div&gt;&lt;p&gt;&lt;strong&gt;"
                "We\u2019re on a mission to make money work for everyone."
                "&lt;/strong&gt;&lt;/p&gt;&lt;/div&gt;"
            ),
            "departments": [{"id": 54075, "name": "Finance"}],
        }
        result = _normalize_job(raw)
        assert result["source"] == "greenhouse"
        assert result["id"] == "8143930"
        assert result["title"] == "Anaplan Support Analyst"
        assert result["company"] == "Monzo"
        assert result["location"] == "Cardiff, London or Remote (UK)"
        assert result["category"] == "Finance"
        assert result["created"] == "2026-08-24T09:04:42-04:00"
        assert result["url"] == "https://job-boards.greenhouse.io/monzo/jobs/8143930"
        assert "mission to make money work" in result["description"]
        assert "<" not in result["description"]

    def test_handles_missing_optional_fields(self):
        raw = {"id": 1, "title": "Data Analyst", "company_name": "Beta Ltd"}
        result = _normalize_job(raw)
        assert result["location"] is None
        assert result["category"] is None
        assert result["description"] is None
        assert result["salary_min"] is None
        assert result["contract_type"] is None

    def test_handles_null_company_and_empty_departments(self):
        raw = {"id": 2, "title": "Data Analyst", "company_name": None, "departments": []}
        result = _normalize_job(raw)
        assert result["company"] is None
        assert result["category"] is None

    def test_strips_company_whitespace(self):
        raw = {"id": 3, "title": "Data Analyst", "company_name": "Acme Corp "}
        result = _normalize_job(raw)
        assert result["company"] == "Acme Corp"


class TestTitleRelevant:
    """Real titles from a live 354-job Greenhouse fetch during ATS ingest -
    not hypothetical cases. Every title expected False here actually
    appeared in that run and wrongly passed the filter before this fix
    existed."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("AI Tutor - Portuguese", False),
            ("AI Success Manager, Central", False),
            ("Data Entry Officer (Delta)", False),
            ("Data Center Operations Technician", False),
            ("Structural Engineer - Data Centers", False),  # plural - caught a real gap
            ("BIM Designer (Data Center)", False),
            ("Data Scientist", True),
            ("Graduate Data Scientist", True),
            ("Machine Learning Engineer", True),
            ("AI Research Engineer", True),
            ("Data Science Manager", True),
            ("AI Product Engineer", True),
        ],
    )
    def test_relevance_with_false_positive_phrases(self, title, expected):
        result = _title_relevant(title, DEFAULT_INCLUDE_WORDS, DEFAULT_FALSE_POSITIVE_PHRASES)
        assert result is expected


class _FlakyHandler(BaseHTTPRequestHandler):
    fail_code = 503
    fail_times = 0
    hit_count = 0

    def do_GET(self):
        type(self).hit_count += 1
        if type(self).hit_count <= type(self).fail_times:
            self.send_response(type(self).fail_code)
            self.end_headers()
            return
        body = json.dumps(
            {
                "jobs": [
                    {
                        "id": 1,
                        "title": "Data Scientist",
                        "company_name": "Test Co",
                        "location": {"name": "London"},
                        "first_published": "2026-01-01T00:00:00Z",
                        "absolute_url": "http://example.test/1",
                        "departments": [],
                    }
                ]
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # keep test output quiet


@pytest.fixture
def flaky_server():
    _FlakyHandler.hit_count = 0
    _FlakyHandler.fail_times = 0
    _FlakyHandler.fail_code = 503
    server = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _FlakyHandler
    server.shutdown()
    thread.join()


class TestRetryBehavior:
    def test_retries_on_503_then_succeeds(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 2  # fail twice, succeed on the 3rd request
        handler.fail_code = 503
        monkeypatch.setattr("jobagg.sources.greenhouse.BASE_URL", base_url)

        jobs = fetch_jobs("test-co")

        assert handler.hit_count == 3
        assert len(jobs) == 1

    def test_does_not_retry_on_401(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 999  # always fail
        handler.fail_code = 401
        monkeypatch.setattr("jobagg.sources.greenhouse.BASE_URL", base_url)

        with pytest.raises(requests.exceptions.HTTPError):
            fetch_jobs("test-co")

        assert handler.hit_count == 1  # no retries attempted


class TestFetchBatch:
    def test_one_bad_token_does_not_crash_the_rest(self):
        """Regression check for a real bug caught during ATS ingest: a DNS
        failure on one company took down an entire 42-company run because
        only HTTPError was caught, not RequestException generally."""

        def fake_fetch_jobs(token, **kwargs):
            if token == "bad-token":
                raise requests.exceptions.ConnectionError("simulated DNS failure")
            return [{"source": "greenhouse", "id": token, "title": "Data Scientist"}]

        with patch("jobagg.sources.greenhouse.fetch_jobs", side_effect=fake_fetch_jobs):
            jobs = fetch_batch(["good-1", "bad-token", "good-2"])

        assert len(jobs) == 2
        assert {j["id"] for j in jobs} == {"good-1", "good-2"}
