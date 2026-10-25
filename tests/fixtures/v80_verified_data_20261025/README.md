# V8.0 verified-data regression fixtures

These are real frozen response extracts through 2026-10-23, not a fabricated
backtest dataset. Manifest entries name original hashes, extraction windows,
source endpoints and derived native-query controls. They contain no credentials.

- Yahoo KMLM is the full archived response with the original omitted distribution.
- Sohu contains actual 2018-11-01..2019-01-31 rows; the 2018-12-14 gap remains.
- Wind bad-long contains an extracted tail of the original long response; its
  request receipt is preserved. The incorrect 10/21 row and absent 10/22,23 remain.
- Wind short and CSI reference are actual 2026-10-19..23 responses.
- CSI 2000 contains 60 actual amount observations, for error-path control only.
- Expected KMLM prices and short CN controls come from the same complete native
  query replay of the independently reviewed repaired source.

Deliberate mutations and synthetic request receipt labels in tests are explicit
counterexamples/control scaffolding. They are not claims of observed vendor events
and must not be used as historical prices. Hashes normalize checkout CRLF to LF;
original source hashes preserve exact archived-response identity.

- Corroborated KMLM actions extract supports the complete suffix-factor check.
  Unknown later actions fail closed pending renewed independent evidence.
