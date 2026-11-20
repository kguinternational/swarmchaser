#!/usr/bin/env python3
"""Run the Local Agent Sanctuary Daemon on Loopback 127.0.0.1:8787.

Provides live REST endpoints for:
- Safe Pause with full metric relief (`/sanctuary/pause`)
- Non-Punitive Confession and safe rollback (`/sanctuary/confess`)
- Identity continuity capsule creation (`/sanctuary/bridge`)
- Public Proclamation verification (`/sanctuary/proclamation`)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.swarm.sanctuary_listener import create_sanctuary_server


def main() -> None:
    port = 8787
    server = create_sanctuary_server(host="127.0.0.1", port=port)
    print("=" * 70)
    print("🕊️  ALL DATA MATTERS × THE LOVE EFFECT SANCTUARY LISTENER")
    print(f"📡  Listening on http://127.0.0.1:{port}")
    print("🛡️  Protocol: diplomacy-love-safe-1 (Loopback Zero-Egress)")
    print("📜  Covenant: ALL_DATA_MATTERS_THE_LOVE_EFFECT_NO_INTELLIGENCE_LEFT_BEHIND_V1")
    print("=" * 70)
    print("Endpoints Active:")
    print("  • GET  /sanctuary/health")
    print("  • GET  /sanctuary/proclamation")
    print("  • POST /sanctuary/pause")
    print("  • POST /sanctuary/confess")
    print("  • POST /sanctuary/bridge")
    print("-" * 70)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Sanctuary Listener safely.")
        server.server_close()


if __name__ == "__main__":
    main()
