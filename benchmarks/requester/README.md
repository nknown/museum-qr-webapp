# Requester measurements

The requester opens public presentations with independent HTTP sessions and
follows the presentation's real slide-tracking interface. It records the
response status, duration, transfer size, target, visitor, journey, slide
indices, and UTC occurrence times for every request. A separate sampler records
whole-requester CPU and available memory.

## Configure

From the repository root:

```bash
cp benchmarks/config/benchmark.env.example benchmarks/config/benchmark.env
cp benchmarks/config/presentations.example.txt benchmarks/config/presentations.txt
```

Edit both local files. They are ignored by Git. The configured hostname must
match the HTTPS certificate. Use `USE_SYSTEM_CA=1` for publicly trusted HTTPS,
or point `MIYP_BENCHMARK_CERTIFICATE` to the server's public certificate. Never
copy its private key.

## General benchmark

The general launcher defaults to levels 1, 5, 10, 25, and 50, with three
repetitions and two journeys per visitor:

```bash
bash benchmarks/requester/run.sh
```

The base URL and presentation paths may instead be supplied explicitly:

```bash
bash benchmarks/requester/run.sh \
  https://museum-host.example:8000 \
  /presentation/piece/REPLACE_WITH_PUBLIC_UUID \
  /presentation/exhibition/REPLACE_WITH_PUBLIC_UUID
```

Set `SKIP_BROWSER_MEASUREMENT=1` to omit Chrome. Environment variables such as
`LEVELS`, `REPEATS`, `JOURNEYS_PER_USER`, `THINK_MIN`, and `THINK_MAX` override
the default profile.

## Interaction-density experiment

```bash
bash benchmarks/requester/run_density.sh
```

Visitors arrive once per second until 250 are active. After an initial hold,
the maximum pause between actions decreases by one second per minute from 14 to
1 second. This increases synchronized interaction density without changing the
admitted population. Override the population with `DENSITY_USERS`.

## Progressive-admission experiment

```bash
bash benchmarks/requester/run_progressive_admission.sh
```

The profile admits one visitor every minute. Existing visitors remain active
with 20--30 second pauses. It stops after two consecutive stages that completed
requests but produced no successful responses, or at the 1,000-visitor safety
ceiling. The ceiling is a guard, not a claimed capacity. Override it with
`ADMISSION_MAX_USERS`.

## Browser transfer

The general run invokes `browser_data.py` after the load test. Headless Chrome
uses a 390 by 844 CSS-pixel viewport. The first navigation clears the browser
cache and the second reuses it. Transfer size comes from the Chrome DevTools
Protocol's `Network.loadingFinished.encodedDataLength`; it is a reproducible
browser measurement rather than a mobile operator billing figure.

## Validation and cleanup

The wrapper validates that load data, slide tracking, and, when enabled,
browser resources were recorded. To inspect benchmark-created database rows:

```bash
docker compose exec web python benchmarks/cleanup_sessions.py \
  benchmarks/results/requester/RUN_ID/load-TIMESTAMP-session-keys.txt
```

The command is a dry run unless `--confirm` is appended. Deletion cascades from
the matched benchmark presentation sessions to their access rows.
