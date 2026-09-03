# vcr.py recordings

Captured once from a live Notion session, replayed by the test suite
(`record_mode="none"` — no network in tests).

**Privacy**: these cassettes are sanitized before being committed.

- request `Cookie` / `Authorization` headers → dropped by
  `filter_headers=["cookie", "authorization"]`
- response `Set-Cookie` headers → dropped by the `before_record_response`
  hook in `tests/test_client.py`. `filter_headers` does NOT cover response
  headers; Notion responses set `file_token`, `device_id` and
  `notion_browser_id`, and a real `file_token` once leaked this way.
- any `token_v2` value left in a body → `FAKE_TOKEN_FOR_TESTS_ONLY`
- personal names, emails, avatar URLs, user/space/page IDs → replaced with
  stable fake values (`Test User`, `test-user@example.com`,
  `11111111-…` / `22222222-…` / `33333333-…`, sample page
  `44444444-…`)

Before committing a cassette, run
`grep -iE 'set-cookie|file_token|token_v2=v0' tests/fixtures/recordings/*.yaml`
and expect no output.

Do NOT re-record cassettes without applying the same sanitization. If a
test needs a new endpoint, capture it against a throwaway workspace with
dummy content, then scrub identity fields before committing.
