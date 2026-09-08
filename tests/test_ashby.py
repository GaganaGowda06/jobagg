"""Tests for jobagg.sources.ashby."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests.adapters import HTTPAdapter

from jobagg.sources.ashby import (
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


class TestNormalizeJob:
    def test_normalizes_real_elevenlabs_posting(self):
        # Trimmed but structurally identical to the real "Account Manager -
        # India" posting fetched live from ElevenLabs's Ashby board.
        posting = {
            "id": "a571b8e4-8176-4e31-aab6-2287ee810236",
            "title": "Account Manager - India ",  # real trailing space
            "department": "Revenue",
            "team": "Revenue - India",
            "employmentType": "FullTime",
            "location": "India",
            "publishedAt": "2026-07-21T16:03:51.100+00:00",
            "isListed": True,
            "jobUrl": "https://jobs.ashbyhq.com/elevenlabs/a571b8e4-8176-4e31-aab6-2287ee810236",
            "descriptionPlain": "ABOUT ELEVENLABS\n\nElevenLabs is an AI research company.",
        }
        result = _normalize_job(posting, company="ElevenLabs")
        assert result["source"] == "ashby"
        assert result["id"] == "a571b8e4-8176-4e31-aab6-2287ee810236"
        assert result["title"] == "Account Manager - India"  # trailing space stripped
        assert result["company"] == "ElevenLabs"
        assert result["location"] == "India"
        assert result["category"] == "Revenue"
        assert result["contract_time"] == "FullTime"
        assert result["contract_type"] is None
        assert result["created"] == "2026-07-21T16:03:51.100+00:00"
        assert result["url"] == posting["jobUrl"]
        assert result["description"] == "ABOUT ELEVENLABS\n\nElevenLabs is an AI research company."
        assert result["salary_min"] is None  # compensation shape not yet confirmed populated

    def test_handles_missing_optional_fields(self):
        posting = {"id": "1", "title": "Data Analyst"}
        result = _normalize_job(posting, company="Beta")
        assert result["location"] is None
        assert result["category"] is None
        assert result["description"] is None
        assert result["contract_time"] is None

    def test_handles_null_title(self):
        posting = {"id": "1", "title": None}
        result = _normalize_job(posting, company="Beta")
        assert result["title"] is None

    def test_strips_title_whitespace(self):
        # Real finding: ElevenLabs's own title field had a trailing space.
        posting = {"id": "1", "title": "  Data Scientist  "}
        result = _normalize_job(posting, company="Beta")
        assert result["title"] == "Data Scientist"

    def test_company_comes_from_argument_not_posting(self):
        # Real finding: like Lever, Ashby postings never include a company
        # field - the caller must always supply it.
        posting = {"id": "1", "title": "Data Analyst"}
        result = _normalize_job(posting, company="Explicit Co")
        assert result["company"] == "Explicit Co"


class TestFetchJobsFiltering:
    def test_unlisted_jobs_excluded(self):
        """Real concern flagged by Ashby's own docs: isListed=false means a
        role shouldn't appear on a public board. Defensive filter, even
        though the endpoint is documented as already-published-only."""
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "jobs": [
                {"id": "1", "title": "Data Scientist", "isListed": True},
                {"id": "2", "title": "Data Analyst", "isListed": False},
            ]
        }
        with patch.object(_session, "get", return_value=resp):
            jobs = fetch_jobs("test-co")
        assert len(jobs) == 1
        assert jobs[0]["id"] == "1"

    def test_missing_is_listed_defaults_to_included(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"jobs": [{"id": "1", "title": "Data Scientist"}]}
        with patch.object(_session, "get", return_value=resp):
            jobs = fetch_jobs("test-co")
        assert len(jobs) == 1

    def test_sends_include_compensation_param(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"jobs": []}
        with patch.object(_session, "get", return_value=resp) as mock_get:
            fetch_jobs("test-co")
        assert mock_get.call_args.kwargs["params"] == {"includeCompensation": "true"}

    def test_relevance_and_exclude_filters_apply(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "jobs": [
                {"id": "1", "title": "Data Scientist", "isListed": True},
                {"id": "2", "title": "Account Manager", "isListed": True},  # not data-relevant
                {"id": "3", "title": "Senior Data Scientist", "isListed": True},  # excluded
            ]
        }
        with patch.object(_session, "get", return_value=resp):
            jobs = fetch_jobs("test-co")
        assert [j["id"] for j in jobs] == ["1"]


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
            {"jobs": [{"id": "1", "title": "Data Scientist", "isListed": True}]}
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
        monkeypatch.setattr("jobagg.sources.ashby.BASE_URL", base_url)

        jobs = fetch_jobs("test-co")

        assert handler.hit_count == 3
        assert len(jobs) == 1

    def test_does_not_retry_on_401(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 999  # always fail
        handler.fail_code = 401
        monkeypatch.setattr("jobagg.sources.ashby.BASE_URL", base_url)

        with pytest.raises(requests.exceptions.HTTPError):
            fetch_jobs("test-co")

        assert handler.hit_count == 1  # no retries attempted


class TestFetchBatch:
    def test_one_bad_company_does_not_crash_the_rest(self):
        def fake_fetch_jobs(name, **kwargs):
            if name == "bad":
                raise requests.exceptions.ConnectionError("simulated failure")
            return [{"source": "ashby", "id": name, "title": "Data Scientist"}]

        with patch("jobagg.sources.ashby.fetch_jobs", side_effect=fake_fetch_jobs):
            jobs = fetch_batch(["good1", "bad", "good2"])

        assert len(jobs) == 2
        assert {j["id"] for j in jobs} == {"good1", "good2"}

    def test_wrong_slug_is_skipped_not_fatal(self):
        """Real scenario from tonight: 'checkout' 404'd, the real slug was
        'checkout.com'. fetch_batch must survive a wrong-slug 404, even
        though fetch_jobs() alone correctly raises for a single bad call."""

        def fake_fetch_jobs(name, **kwargs):
            if name == "checkout":
                resp = MagicMock(status_code=404)
                raise requests.exceptions.HTTPError(response=resp)
            return [{"source": "ashby", "id": name, "title": "Data Scientist"}]

        with patch("jobagg.sources.ashby.fetch_jobs", side_effect=fake_fetch_jobs):
            jobs = fetch_batch(["elevenlabs", "checkout", "cohere"])

        assert {j["id"] for j in jobs} == {"elevenlabs", "cohere"}
