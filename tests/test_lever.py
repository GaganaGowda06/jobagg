"""Tests for jobagg.sources.lever."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests.adapters import HTTPAdapter

from jobagg.sources.lever import (
    _build_description,
    _clean_html,
    _fetch_postings,
    _normalize_job,
    _retry,
    _session,
    fetch_batch,
    fetch_jobs,
)

# Same gotcha as every other source's tests tonight: the retry adapter is
# only mounted for https://. The local test server below is plain http://,
# so the same retry policy is mounted here too.
_session.mount("http://", HTTPAdapter(max_retries=_retry))


class TestCleanHtml:
    def test_strips_tags(self):
        assert _clean_html("<div><p>Hello</p></div>") == "Hello"

    def test_unescapes_entities(self):
        assert _clean_html("<li>DE&amp;I forum</li>") == "DE&I forum"

    def test_handles_none(self):
        assert _clean_html(None) is None

    def test_handles_empty_string(self):
        assert _clean_html("") is None


class TestBuildDescription:
    def test_combines_opening_and_lists(self):
        # Real shape from Zopa's "2027 Graduate Analyst" posting: the salary
        # and requirements live in lists, not descriptionPlain.
        posting = {
            "descriptionPlain": "Our Story. Hello there, we're Zopa.",
            "lists": [
                {"text": "What can Zopa offer you?", "content": "<li>\u00a345,000 salary</li>"},
            ],
        }
        result = _build_description(posting)
        assert "Hello there, we're Zopa" in result
        assert "What can Zopa offer you?" in result
        assert "\u00a345,000 salary" in result

    def test_falls_back_to_opening_plain_when_description_plain_missing(self):
        posting = {"openingPlain": "Fallback intro text.", "lists": []}
        result = _build_description(posting)
        assert result == "Fallback intro text."

    def test_handles_missing_lists(self):
        posting = {"descriptionPlain": "Just an intro."}
        assert _build_description(posting) == "Just an intro."

    def test_handles_nothing_present(self):
        assert _build_description({}) is None


class TestNormalizeJob:
    def test_normalizes_real_zopa_posting(self):
        # Trimmed but structurally identical to the real "2027 Graduate
        # Analyst" posting fetched from Zopa's live Lever site.
        posting = {
            "id": "962f3756-6e45-480f-984c-64e024b57c4f",
            "text": "2027 Graduate Analyst",
            "categories": {
                "commitment": "Employee - Permanent",
                "department": "CAO General",
                "location": "London",
            },
            "createdAt": 1787913476287,
            "descriptionPlain": "Our Story. Hello there, we're Zopa.",
            "lists": [{"text": "What can Zopa offer you?", "content": "<li>Salary info</li>"}],
            "hostedUrl": "https://jobs.lever.co/zopa/962f3756-6e45-480f-984c-64e024b57c4f",
        }
        result = _normalize_job(posting, company="Zopa")
        assert result["source"] == "lever"
        assert result["id"] == "962f3756-6e45-480f-984c-64e024b57c4f"
        assert result["title"] == "2027 Graduate Analyst"
        assert result["company"] == "Zopa"
        assert result["location"] == "London"
        assert result["contract_type"] == "Employee - Permanent"
        assert result["category"] == "CAO General"
        assert result["url"] == posting["hostedUrl"]
        assert result["created"].startswith("2026-")  # sane converted year
        assert "Salary info" in result["description"]

    def test_handles_missing_categories(self):
        posting = {"id": "1", "text": "Data Analyst"}
        result = _normalize_job(posting, company="Beta")
        assert result["location"] is None
        assert result["contract_type"] is None
        assert result["category"] is None

    def test_handles_missing_created_at(self):
        posting = {"id": "1", "text": "Data Analyst"}
        result = _normalize_job(posting, company="Beta")
        assert result["created"] is None

    def test_company_comes_from_argument_not_posting(self):
        # Real finding: Lever's own postings never include a company field -
        # the caller must always supply it.
        posting = {"id": "1", "text": "Data Analyst"}
        result = _normalize_job(posting, company="Explicit Co")
        assert result["company"] == "Explicit Co"


class TestFetchPostingsFallback:
    def test_global_host_succeeds_no_fallback_needed(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = [{"id": "1", "text": "Data Scientist"}]
        with patch.object(_session, "get", return_value=resp) as mock_get:
            result = _fetch_postings("some-co")
        assert result == [{"id": "1", "text": "Data Scientist"}]
        assert mock_get.call_count == 1  # never needed to try the EU host

    def test_falls_back_to_eu_host_on_404(self):
        resp_404 = MagicMock(status_code=404)
        resp_ok = MagicMock(status_code=200)
        resp_ok.json.return_value = [{"id": "1", "text": "Data Scientist"}]

        def fake_get(url, params=None):
            return resp_404 if "eu" not in url else resp_ok

        with patch.object(_session, "get", side_effect=fake_get):
            result = _fetch_postings("eu-only-co")
        assert result == [{"id": "1", "text": "Data Scientist"}]

    def test_falls_back_to_eu_host_on_connection_error(self):
        """Regression check for the exact failure mode that crashed
        Greenhouse: a connection-level failure (not a bad status code) on
        the first host must not prevent trying the second."""
        resp_ok = MagicMock(status_code=200)
        resp_ok.json.return_value = [{"id": "1", "text": "Data Scientist"}]

        def fake_get(url, params=None):
            if "eu" not in url:
                raise requests.exceptions.ConnectionError("simulated DNS failure")
            return resp_ok

        with patch.object(_session, "get", side_effect=fake_get):
            result = _fetch_postings("some-co")
        assert result == [{"id": "1", "text": "Data Scientist"}]

    def test_both_hosts_failing_raises_clearly(self):
        resp_404 = MagicMock(status_code=404)
        with (
            patch.object(_session, "get", return_value=resp_404),
            pytest.raises(requests.exceptions.HTTPError),
        ):
            _fetch_postings("totally-fake-co")


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
        body = json.dumps([{"id": "1", "text": "Data Scientist", "categories": {}}]).encode()
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
        monkeypatch.setattr("jobagg.sources.lever.GLOBAL_BASE_URL", base_url)

        jobs = fetch_jobs("test-co")

        assert handler.hit_count == 3
        assert len(jobs) == 1

    def test_does_not_retry_on_401(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 999  # always fail
        handler.fail_code = 401
        monkeypatch.setattr("jobagg.sources.lever.GLOBAL_BASE_URL", base_url)

        with pytest.raises(requests.exceptions.HTTPError):
            fetch_jobs("test-co")

        assert handler.hit_count == 1  # no retries attempted, no EU fallback either


class TestFetchBatch:
    def test_one_bad_company_does_not_crash_the_rest(self):
        def fake_fetch_jobs(slug, **kwargs):
            if slug == "bad":
                raise requests.exceptions.ConnectionError("simulated failure")
            return [{"source": "lever", "id": slug, "title": "Data Scientist"}]

        with patch("jobagg.sources.lever.fetch_jobs", side_effect=fake_fetch_jobs):
            jobs = fetch_batch(["good1", "bad", "good2"])

        assert len(jobs) == 2
        assert {j["id"] for j in jobs} == {"good1", "good2"}
