# vendored: specs/signal-export

Frozen copies of the `signal-export` contract family (schemas + test vectors)
that `cerebro/sink/export.py` serializes into. Vendored so cerebro's test suite
can validate its exporter output offline **without depending on the kernel
repo** (the contract lives in a separate, partly-closed repo; cerebro is
Apache-2.0 and standalone).

If the upstream contract changes, re-copy these files and update the SHAs below.
A test (`tests/test_conformance.py`) pins the vendored `research-signal` schema
against a fingerprint from `valid.json`, so a silent drift in the
canonicalization surfaces as a failing test rather than a wrong export.

## Source

- Repo: `stevengonsalvez/fleet-lambda` (contracts checkout), path
  `specs/signal-export/`
- Commit: `0af7bf4f58b245c9f8d9d9ee6103a4a2edd9b449`
  (`style(contracts): use colons not em-dashes in goal 09 docstrings`)
- Contract: research-signal + tried-ledger-entry, `schemaVersion: 1`
- License: Apache-2.0

## Contents and SHA-256

```
7d0f9d7e6a57077214a2ca4f4afc136c73b542353269c8be6416e3dc8c5e2fe2  schemas/research-signal.schema.json
8bff97dab440ff2c0ae3cbcf22fd2fc32dbee2c82b02d9155a764c3eca8f22fb  schemas/tried-ledger-entry.schema.json
d2f5f68c04224070f676d65fb039f1744bd9fda256ca1137a471ba46d2f3df81  test-vectors/research-signal/invalid-bad-fingerprint.json
356dadb5e718d0976da883d6653c6f72982e1abbe4461ae18f9715fecc906883  test-vectors/research-signal/invalid-missing-tenant.json
1e4ef3bd390b36b4be28242631c65181c04017212230ef497ef48b868957770d  test-vectors/research-signal/invalid-score-out-of-range.json
3cefd6311525bc64f518d7e8379ffa4db57d38779775772337186105877b3e39  test-vectors/research-signal/invalid-unknown-source.json
8b57e3ba74285ac18e3358a25af2c0ff92664f5050ba99a8021e249a0f32f00a  test-vectors/research-signal/invalid-wrong-schema-version.json
d785373c2925f7d5b68fad6f24a4ce39f0ab0b7252577d1164c7d731a568b334  test-vectors/research-signal/valid-content-basis.json
f5a5950960ca967e6d4ba5f5cda454928751b5066a92fe728dabf61dd6deeb2d  test-vectors/research-signal/valid-reflect.json
188195fa0844adbc412135859e9874e8b8eeda5b38144eff3c4d68a1986c2e18  test-vectors/research-signal/valid.json
3108aa72581a395cb6bcede9edf977cbc22f6e80d1b4fd5213646606b9d6e302  test-vectors/tried-ledger-entry/invalid-bad-status.json
f8be3fe266372a238287afeb8efd8ce80f2acbdf0f7b8bccb1d0a706b5665756  test-vectors/tried-ledger-entry/invalid-rejected-missing-reason.json
1c716b934b0baa99bbd1f275e60db8b98af2f3e34cd91143e8da654840318b4a  test-vectors/tried-ledger-entry/invalid-rejected-missing-revisit.json
e346a6d30d17979b44402b161d4d9992fef7e3e3e98ba0e982d0238d0876c064  test-vectors/tried-ledger-entry/valid-adopted.json
4de025cddb542463bfa39dee0c655a9f792c7faa649fd08549aa7acbfc09a587  test-vectors/tried-ledger-entry/valid-pending.json
78dafc00506c56e27c9da5b4af19a4a6bdcca1f333b23bf55edecdf458dc150d  test-vectors/tried-ledger-entry/valid-rejected.json
```

Vector naming (upstream convention): a vector prefixed `invalid-` MUST fail
schema validation; every other vector MUST pass. The kind is the subdirectory
name.
