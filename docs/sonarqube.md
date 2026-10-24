# SonarQube (Phase 17)

## What it is for

| Question | Tool |
|---|---|
| Is the style consistent? | ruff |
| Does the code behave? | pytest |
| Does a dependency or image have a known CVE? | pip-audit, npm audit, Trivy |
| Did someone commit a secret? | gitleaks |
| Is OUR code buggy, insecure, hard to maintain, or untested? | **SonarQube** |

## Flow

```
pytest --cov (per service)  -> coverage.xml  -> prefix_coverage.py (file names relative to repo root)
vitest --coverage (frontend)-> lcov.info
                                   \                         
                                    sonarqube-scan-action -> SonarQube server -> quality gate -> pass/fail in the PR
```

Coverage files only say "line 12 of api/payments.py ran". SonarQube needs to know which file in the repository that is,
which is why `scripts/ci/prefix_coverage.py` rewrites the names.

## Vocabulary

- **Bug**: code that is probably wrong. **Vulnerability**: exploitable weakness. **Security hotspot**: sensitive code a human must judge. **Code smell**: maintainability problem.
- **New code**: what changed since the baseline (the previous version or the main branch). The gate looks only at it.
- **Quality gate**: a pass/fail rule set. Ours: `school-gate`.

## Commands

```bash
scripts/ci/sonar-local.sh start                  # local server, http://localhost:9000
scripts/ci/sonar-local.sh scan <token>           # tests with coverage, then analysis
scripts/ci/sonar-local.sh stop
SONAR_HOST_URL=... SONAR_TOKEN=... scripts/ci/sonar-quality-gate.sh   # create/apply the gate
curl -s -u "$SONAR_TOKEN:" "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=school-management"
```

## Troubleshooting: quality gate failed

| Symptom | Look at | Fix |
|---|---|---|
| "Coverage on new code 62% < 80%" | the PR's SonarQube page, Measures, Coverage, filter to new code | add tests for the listed lines |
| coverage 0% everywhere | scan log: "Cannot find coverage report" / "unresolved paths" | file names in coverage.xml do not match the repository: check `prefix_coverage.py` ran and the artifact was copied to `services/<name>/coverage.xml` |
| a new issue | click it; the rule page explains the problem and a fix | fix it; if it is a false positive, mark it "Accepted"/"False positive" in SonarQube with a comment |
| scan fails "Not authorized" / 401 | `SONAR_TOKEN` | token expired or lacks Execute Analysis permission |
| scan fails "connection refused" / timeout | `SONAR_HOST_URL` | GitHub runners cannot reach a localhost or private server |
| quality-gate step times out | server background tasks (Administration, Projects, Background Tasks) | server overloaded or the analysis failed server-side |
