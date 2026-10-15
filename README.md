# DAC Interstellar Bot

Auto-farm bot for [interstellar.dachain.io](https://interstellar.dachain.io) (Chip Entropico game).

## What it does
- **Claim-when-full**: claims the mining cache to balance ONLY when the cache is completely full (never early).
- **Auto-upgrade**: buys chip levels up to max while the QE balance covers the next cost.
- **Daily check-in**: +10 QE/day streak (7-day streak = 500 QE badge), via real-Chrome CAP solve.

## Setup
```bash
cp session.txt.example session.txt   # paste your django sessionid cookie
pip install playwright && playwright install chrome  # or use system chrome
```

## Run
```bash
python3 dac_bot.py               # full run (claim/upgrade/check-in)
python3 dac_bot.py --no-browser  # curl-only (no CAP/check-in)
```

## How
- Game actions (`/api/v1/game/cache/claim/`, `/api/v1/game/chip/purchase/`) work over plain HTTP while the ~12h game session is alive.
- The game session + daily check-in are gated by a PoW CAP (`cap.dachain.tech`), which blocks headless browsers (`automated_browser_detected`). `cap_flow.py` runs real Chrome headed under `xvfb-run -a` to solve it.
- Cron example: `*/30 * * * * cd /path && python3 dac_bot.py >/dev/null 2>&1`

## Files
- `dac_bot.py` — main loop (state → claim-when-full → upgrade loop → check-in)
- `cap_flow.py` — browser mode CAP session refresh + check-in click
- `session.txt` — your session cookie (gitignored)
