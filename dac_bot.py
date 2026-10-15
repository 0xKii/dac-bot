#!/usr/bin/env python3
"""DAC Interstellar bot — auto claim + upgrade + check-in.

Rules (per Ki):
- Claim cache ONLY when full (amount >= capacity). Don't claim early.
- Upgrade chip to max when balance allows (keep buying while next_cost <= balance).
- Daily check-in via cap_flow.py (browser mode under xvfb), only if not yet checked in.

Usage:
  /usr/bin/python3 dac_bot.py            # full run (claim/upgrade as needed + checkin)
  /usr/bin/python3 dac_bot.py --no-browser   # curl-only actions, skip check-in refresh

Auth: sessionid cookie in /root/dac-bot/session.txt (rotate when expired).
Game session (CAP) is refreshed by cap_flow.py via real Chrome under xvfb every cron run.
"""
import json, subprocess, sys, uuid, datetime as dt
import urllib.request

BASE = "https://interstellar.dachain.io"
LOG = "/root/dac-bot/dac_bot.log"
RESULT = "/root/dac-bot/last_run.json"

def log(msg):
    line = f"[{dt.datetime.now(dt.timezone(dt.timedelta(hours=7))):%Y-%m-%d %H:%M:%S WIB}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def api(path, method="GET", body=None, csrf=None):
    cookies = f"sessionid={SESSION}"
    if csrf:
        cookies += f"; csrftoken={csrf}"
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
         "Referer": f"{BASE}/", "Cookie": cookies}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if csrf:
        h["X-CSRFToken"] = csrf
    req = urllib.request.Request(f"{BASE}{path}", data=payload, headers=h, method=method)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"success": False, "error": {"code": f"HTTP{e.code}"}}

def get_csrf():
    # CSRF endpoint: GET sets csrftoken cookie; read it from Set-Cookie.
    req = urllib.request.Request(f"{BASE}/api/v1/auth/csrf/",
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                 "Accept": "application/json", "Referer": f"{BASE}/",
                 "Origin": BASE, "Cookie": f"sessionid={SESSION}"})
    resp = urllib.request.urlopen(req, timeout=20)
    for k, v in resp.headers.items():
        if k.lower() == "set-cookie" and "csrftoken" in v:
            return v.split("csrftoken=")[1].split(";")[0]
    return None

def game_state():
    return api("/api/v1/game/state/")

def claim_cache(csrf):
    key = f"claim-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    return api("/api/v1/game/cache/claim/", "POST", {"idempotency_key": key}, csrf)

def buy_chip(csrf):
    key = f"buy-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    return api("/api/v1/game/chip/purchase/", "POST", {"idempotency_key": key}, csrf)

def checkin_status():
    return api("/api/v1/checkin/")

# ---- main ----
SESSION = open("/root/dac-bot/session.txt").read().strip()
no_browser = "--no-browser" in sys.argv

result = {"ts": dt.datetime.now(dt.UTC).isoformat(), "claimed": None, "upgrades": 0,
          "checkin": None, "level": None, "cache": None, "balance": None, "errors": []}

st = game_state()
if not st.get("success"):
    code = st.get("error", {}).get("code")
    log(f"FATAL: game state failed: {code}")
    result["errors"].append(code)
    json.dump(result, open(RESULT, "w"), indent=1)
    sys.exit(1)

d = st["data"]
chip, cache, bal = d["chip"], d["cache"], d["qe_balance"]
lvl = chip["level"]
amount = float(cache["amount_qe"])
capacity = float(cache["capacity_qe"])
log(f"level={lvl} cache={amount:.0f}/{capacity:.0f} QE prod={cache['production_qe_per_sec']} balance={bal}")

# ---- 1) claim only when FULL ----
if amount >= capacity:
    csrf = get_csrf()
    r = claim_cache(csrf)
    if r.get("success"):
        bal = r["data"]["qe_balance"]
        log(f"CLAIMED {amount:.0f} QE -> balance {bal}")
        result["claimed"] = amount
    else:
        log(f"claim failed: {r.get('error',{}).get('code')}")
        result["errors"].append(f"claim:{r.get('error',{}).get('code')}")
        # if session died, try browser refresh once
        if r.get("error", {}).get("code") in ("GAME_HUMAN_CHECK_REQUIRED", "PERMISSION_DENIED"):
            log("session stale — attempting browser refresh via cap_flow.py")
            if not no_browser:
                subprocess.run(["xvfb-run", "-a", "/usr/bin/python3", "/root/dac-bot/cap_flow.py"],
                               timeout=180, capture_output=True)
                st = game_state()
                if st.get("success"):
                    d = st["data"]
                    chip, cache, bal = d["chip"], d["cache"], d["qe_balance"]
                    r = claim_cache(get_csrf())
                    if r.get("success"):
                        bal = r["data"]["qe_balance"]
                        log(f"RETRY claim OK -> balance {bal}")
                        result["claimed"] = amount

# ---- 2) upgrade while affordable ----
upgrades = 0
csrf = get_csrf()
while True:
    st = game_state()
    if not st.get("success"):
        result["errors"].append("state_mid_upgrade")
        break
    d = st["data"]
    chip, bal = d["chip"], d["qe_balance"]
    cost = float(chip["next_cost_qe"]) if chip["next_cost_qe"] else None
    if cost is None or chip["level"] >= chip["max_level"]:
        log(f"max level or no cost: level={chip['level']}")
        break
    if float(bal) < cost:
        log(f"can't upgrade: balance {bal} < next cost {chip['next_cost_qe']}")
        break
    r = buy_chip(csrf)
    if r.get("success"):
        upgrades += 1
        bal = r["data"]["qe_balance"]
        lvl = r["data"]["chip"]["level"]
        log(f"upgraded -> level {lvl}, balance {bal}")
    else:
        code = r.get("error", {}).get("code")
        log(f"upgrade failed: {code}")
        result["errors"].append(f"upgrade:{code}")
        break
result["upgrades"] = upgrades

# ---- 3) daily check-in ----
if not no_browser:
    ci = checkin_status()
    if ci.get("success"):
        if not ci["data"]["checked_in_today"]:
            log("check-in due — running browser flow")
            p = subprocess.run(["xvfb-run", "-a", "/usr/bin/python3", "/root/dac-bot/cap_flow.py"],
                               timeout=180, capture_output=True, text=True)
            try:
                fr = json.load(open("/root/dac-bot/flow_result.json"))
                result["checkin"] = fr.get("checkin")
            except Exception:
                result["checkin"] = "unknown"
            ci2 = checkin_status()
            if ci2.get("success"):
                log(f"check-in now: checked_in_today={ci2['data']['checked_in_today']} streak={ci2['data']['streak']}")
        else:
            log("already checked in today")
            result["checkin"] = "already"
    else:
        result["errors"].append("checkin_status")

# final state
st = game_state()
if st.get("success"):
    d = st["data"]
    result["level"] = d["chip"]["level"]
    result["cache"] = d["cache"]["amount_qe"]
    result["balance"] = d["qe_balance"]
    log(f"FINAL level={result['level']} cache={result['cache']} balance={result['balance']}")
json.dump(result, open(RESULT, "w"), indent=1)
log("done")
