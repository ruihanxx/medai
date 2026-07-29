---
name: get-available-resources
description: Record CPU, memory, disk, and NVIDIA GPU capacity before full-scale computation.
---

# Get Available Resources

Run `scripts/detect_resources.py --path WORKSPACE --output resources.json` and
size data loading, batches, workers, and accelerator use from that evidence.
