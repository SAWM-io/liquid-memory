# Validation of this reference example

Checked on 24 October 2026 using Python 3.13, before initial publication.

- 15 tests passed, with the pinned public SDK installed.
- The default synthetic demo completed without credentials or Cloud calls.
- Tests cover writes with lost responses, retry after restart, changed-input
  conflicts, pending receipts, world isolation, source retention, revision
  history, unavailable ODVL, explicit historical recall and malformed scope.
- A six-request SDK contract test uses the actual downloaded SDK with
  `httpx.MockTransport`: entity creation, initial assertion, revision, TSST
  recall, TSST flashback and ODVL observation. It checks serialized payloads.
- Expired uncertain operations are blocked; old confirmed memories remain readable.
- SDK checksum failure leaves the previously installed file unchanged.
- Python syntax and local documentation links passed checks; both original
  SVG illustrations were rendered and visually inspected.

Reproduce from the repository root:

```sh
python -m pip install -r requirements.txt
python bootstrap_sdk.py
python -m unittest discover -s tests -v
python demo.py
```

Without the downloaded SDK, its contract test is explicitly skipped; the other
14 tests need only the Python standard library.

No authenticated live Cloud writes or live LLM character tests were performed
for this repository release. These tests do not measure retrieval recall,
semantic action correctness, emotional realism, latency, billing, or endurance
across months and years. Running `--cloud` is an explicit, metered integration
exercise in your own authorized space.
