# AutoDL Container Instance Pro API operations

Use this guide to inspect, power on, power off, or release an existing AutoDL
Container Instance Pro instance. It is a manual operator guide, not a
replacement for the run-owned `templates/skills/computation_provider` workflow.
That workflow must only operate on instances recorded in the current run's
`remote_compute/instance.json` with `created_by_run: true`.

## Prerequisites

Run commands from the repository root. The project `.env` must contain
`AUTODL_TOKEN`; `AUTODL_API_BASE_URL` is optional and defaults to the public API
origin. Do not print or commit the token.

```bash
set -a
. ./.env
set +a

: "${AUTODL_TOKEN:?AUTODL_TOKEN is required}"
AUTODL_API_BASE_URL="${AUTODL_API_BASE_URL:-https://api.autodl.com}"
INSTANCE_UUID="pro-..."
```

Replace `pro-...` with the exact UUID selected from the instance list or the
run-owned state file. Confirm the target in the AutoDL console before a power
or release operation.

Define this helper once for the current shell. It reads the token only from the
environment and never places it in a command argument or output. `POST` sends
JSON; `GET` encodes its payload as URL query parameters.

```bash
autodl_api() {
  AUTODL_METHOD="$1" AUTODL_PATH="$2" AUTODL_PAYLOAD="$3" python - <<'PY'
import json
import os
import urllib.parse
import urllib.request

method = os.environ["AUTODL_METHOD"]
path = os.environ["AUTODL_PATH"]
payload = json.loads(os.environ["AUTODL_PAYLOAD"])
base_url = os.environ["AUTODL_API_BASE_URL"].rstrip("/")
url = base_url + path
data = json.dumps(payload).encode("utf-8")
headers = {"Authorization": os.environ["AUTODL_TOKEN"], "Content-Type": "application/json"}
if method == "GET":
    url += "?" + urllib.parse.urlencode(payload)
    data = None
    headers.pop("Content-Type")
request = urllib.request.Request(url, data=data, method=method, headers=headers)
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.read().decode("utf-8"))
PY
}
```

## List existing Pro instances

The list endpoint is read-only. Its response contains each instance's `uuid`,
`created_at`, and `status`.

For normal use, run the included helper. It reads the repository-root `.env` by
default and prints the complete API response:

```bash
python3 scripts/list_autodl_pro_instances.py
```

Pass an alternate local dotenv file only when needed:

```bash
python3 scripts/list_autodl_pro_instances.py --env-file /absolute/path/to/.env
```

The equivalent raw API call is:

```bash
autodl_api POST /api/v1/dev/instance/pro/list '{"page_index":1,"page_size":100}'
```

To read one known instance's status, use a URL query parameter. Do not send a
JSON request body with this GET request: the current API returns a parameter
error for that form.

```bash
autodl_api GET /api/v1/dev/instance/pro/status "{\"instance_uuid\":\"$INSTANCE_UUID\"}"
```

`"code":"Success"` confirms the API operation succeeded. Typical lifecycle
states include `running` and `shutdown`; wait for `shutdown` before releasing.

## Power on

Powering on allocates the recorded GPU resource and may start billing. Do not
use it as an availability probe.

```bash
autodl_api POST /api/v1/dev/instance/pro/power_on \
  "{\"instance_uuid\":\"$INSTANCE_UUID\",\"payload\":\"gpu\",\"start_command\":\"sleep 1\"}"
```

Use the status command above until it reports `running` before connecting or
starting work.

## Power off

Powering off stops the instance but does not release it. Its data may remain
available under AutoDL's retention rules.

```bash
autodl_api POST /api/v1/dev/instance/pro/power_off \
  "{\"instance_uuid\":\"$INSTANCE_UUID\"}"
```

Query status until it reports `shutdown`.

## Release

Release is irreversible and destroys the instance's local data. First download
all required outputs and evidence, then power off and confirm `shutdown`.

```bash
autodl_api POST /api/v1/dev/instance/pro/release \
  "{\"instance_uuid\":\"$INSTANCE_UUID\"}"
```

For a MedAI run, after a successful release, update only through the AutoDL
provider script so its run state records `released: true`. Do not hand-edit the
state file.

## Reference

- [AutoDL Container Instance Pro API](https://www.autodl.com/docs/instance_pro_api/)
