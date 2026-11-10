# Security

## Reporting

Report vulnerabilities privately to the repository owner via GitHub
Security Advisories ("Report a vulnerability" on the Security tab).
Please do not open a public issue for a security problem.

## Safety model

CI Command Truth is **static only**:

- It never executes code, scripts, or workflow commands from a scanned
  repository. There is no `subprocess`, `eval`, `exec`, or `os.system`
  anywhere in the tool (a unit test asserts this).
- It makes no network requests and has no dependencies beyond the
  Python 3 standard library.
- All file reads are size-capped (1 MB per file; oversized workflow
  files are reported as unscanned rather than read).
- Paths from workflow files are only ever used for existence checks
  inside the scanned root; nothing is written to the scanned tree.

Scanning an untrusted repository is therefore safe by construction:
the worst a hostile workflow can do is be reported as unscanned.
