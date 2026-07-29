---
name: autodl
description: Rent and operate AutoDL GPU compute when the paper requires a GPU unavailable locally.
---

# AutoDL

Use `scripts/autodl.py` only after recording a concrete GPU requirement.

```bash
python scripts/autodl.py create --gpu-spec SPEC --gpu-count N --state STATE.json
python scripts/autodl.py upload --state STATE.json --source CODEBASE --remote /root/autodl-tmp/run
python scripts/autodl.py exec --state STATE.json -- COMMAND...
python scripts/autodl.py download --state STATE.json --remote /root/autodl-tmp/run/results --destination RESULTS
python scripts/autodl.py release --state STATE.json
```

`AUTODL_TOKEN` and `AUTODL_IMAGE_UUID` must be configured. Use the GPU spec
required by the paper. Do not silently select a smaller GPU, reduce experiment
scale, or release an instance not created by the current run.
