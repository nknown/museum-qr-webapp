# Server monitoring

`monitor_server.sh` samples the application host once per second by default. It
records:

- whole-host CPU, memory, and one-minute load average;
- per-service CPU, memory, network I/O, block I/O, and process count;
- total and active database connections and the configured connection limit;
- proxy request activity and time since the last request;
- interaction-density and progressive-admission phase markers;
- a final idle interval after the requester reports completion.

Outputs are written under `benchmarks/results/server/RUN_ID/` as
`server-samples.csv`, `server-metadata.json`, `server-events.log`, and a
controller log.

## Run

Start the Compose deployment, then run from the repository root:

```bash
bash benchmarks/server/monitor_server.sh
```

The monitor automatically uses the repository directory name as the Compose
project name. If the deployment was started with another project name, set it:

```bash
COMPOSE_PROJECT_NAME=my-deployment \
  bash benchmarks/server/monitor_server.sh
```

The defaults match this repository's `docker-compose.yml`. Other deployments
can override `WEB_SERVICE`, `DATABASE_SERVICE`, `PROXY_SERVICE`,
`POSTGRES_USER`, and `POSTGRES_DB`. Sampling and recovery duration are
controlled by `SAMPLE_INTERVAL_SECONDS` and `FINAL_IDLE_SECONDS`.

The script uses the current user's Docker access when available. Otherwise it
asks for `sudo` once and restores ownership of the generated result directory
when monitoring ends.

## Coordination

Requester scripts send special marker requests through the proxy when a phase
changes and when a run finishes. The monitor reads those entries from the
proxy's timestamped container log; the marker endpoint does not need to be an
application feature. After the completion marker, monitoring continues until
the configured idle interval has been observed so recovery can be measured.

Press `Ctrl+C` to stop manually if the requester cannot send its completion
marker. Server and requester clocks should be synchronized before an academic
experiment so their UTC timelines can be aligned accurately.
