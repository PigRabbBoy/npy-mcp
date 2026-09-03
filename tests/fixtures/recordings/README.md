# vcr.py recordings

Captured once from a live Notion session, replayed by the test suite
(`record_mode="none"` — no network in tests).

**Privacy**: these cassettes are sanitized before being committed.

- `token_v2` / cookies → replaced with `FAKE_TOKEN_FOR_TESTS_ONLY` at
  record time (`filter_headers=["cookie", "authorization"]` + manual scrub)
- personal names, emails, avatar URLs, user/space/page IDs → replaced with
  stable fake values (`Test User`, `test-user@example.com`,
  `11111111-…` / `22222222-…` / `33333333-…`, sample page
  `44444444-…`)

Do NOT re-record cassettes without applying the same sanitization. If a
test needs a new endpoint, capture it against a throwaway workspace with
dummy content, then scrub identity fields before committing.
