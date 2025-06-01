# OrcaOps 🐳⚙️
*A lightweight, Python‑first wrapper around the Docker Engine.*

**Why “Orca”?**  
Docker’s logo is a whale; an orca is the apex whale. OrcaOps aims to give your containers the same edge—fast, smart, streamlined.

## Quick Start
```bash
# Build and tag the project image
python -m orcaops build

# Spin up services defined in sandboxes.yml
python -m orcaops up

# Tear everything down
python -m orcaops down
