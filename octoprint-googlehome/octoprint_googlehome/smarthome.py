# coding=utf-8
"""Pure SYNC/QUERY/EXECUTE response building for Google's Smart Home Actions
cloud-to-cloud fulfillment protocol (https://developers.home.google.com/cloud-to-cloud).

Deliberately framework-free (no Flask, no OctoPrint imports) so it's testable with
plain dicts in/out, mirroring how shelly.py/nano.py stay framework-free in the
sibling plugins.

Design note on the Modes trait: Google requires the full closed set of valid
mode values to be declared upfront in SYNC -- QUERY can only report one of
those pre-declared values, never arbitrary free text. Rather than maintaining
an ever-growing list of every F1 circuit name (fragile, needs updating every
time a new circuit is tracked), ACTIVITY_VALUES stays a small fixed set and
F1 tracking simply reports "gara" (race) generically, not which circuit. This
is a deliberate scope reduction, not an oversight -- see the plan file.
"""

DEVICE_ID = "sandtable"
DEVICE_ID_LUCE = "luci_tavolo"
# SWITCH, not VACUUM. VACUUM passes Google's *certification* device-requirements
# check (StartStop-only), but VACUUM devices are historically not selectable as
# Google Home Routine actions (greyed out / invisible in the routine builder),
# which is the one thing we actually need: mapping the "salta questo disegno"
# phrase to a skip. SWITCH is reliably routine-controllable and is the config
# that demonstrably worked end-to-end. We don't need certification (single
# household, draft mode), so the SWITCH "requires OnOff" cert warning is moot.
DEVICE_TYPE = "action.devices.types.SWITCH"
TRAIT_MODES = "action.devices.traits.Modes"
TRAIT_STARTSTOP = "action.devices.traits.StartStop"

ACTIVITY_RIPOSO = "riposo"
ACTIVITY_PULIZIA = "pulizia"
ACTIVITY_DISEGNO = "disegno"
ACTIVITY_GARA = "gara"
ACTIVITY_VALUES = (ACTIVITY_RIPOSO, ACTIVITY_PULIZIA, ACTIVITY_DISEGNO, ACTIVITY_GARA)

_ACTIVITY_SYNONYMS = {
    ACTIVITY_RIPOSO: ["riposo", "inattivo", "fermo"],
    ACTIVITY_PULIZIA: ["pulizia", "cancellazione"],
    ACTIVITY_DISEGNO: ["disegno", "disegno della sabbia"],
    ACTIVITY_GARA: ["gara", "formula 1", "f1"],
}


def build_sync_response(request_id, device_name):
    """SYNC: declares two devices — Tavolo (drawing control) + Luci Tavolo (LED effects)."""
    return {
        "requestId": request_id,
        "payload": {
            "agentUserId": "sandtable-household",
            "devices": [
                {
                    "id": DEVICE_ID,
                    "type": DEVICE_TYPE,
                    "traits": [TRAIT_MODES, TRAIT_STARTSTOP],
                    "name": {
                        "defaultNames": ["Tavolo da Disegno"],
                        "name": device_name,
                        "nicknames": [device_name],
                    },
                    "willReportState": False,
                    "attributes": {
                        "availableModes": [
                            {
                                "name": "activity",
                                "name_values": [
                                    {"lang": "it", "name_synonym": ["attività", "attivita"]}
                                ],
                                "settings": [
                                    {
                                        "setting_name": value,
                                        "setting_values": [
                                            {"lang": "it", "setting_synonym": _ACTIVITY_SYNONYMS[value]}
                                        ],
                                    }
                                    for value in ACTIVITY_VALUES
                                ],
                                "ordered": False,
                            }
                        ],
                        "pausable": False,
                    },
                },
                {
                    "id": DEVICE_ID_LUCE,
                    "type": DEVICE_TYPE,
                    "traits": [TRAIT_STARTSTOP],
                    "name": {
                        "defaultNames": ["Luci Tavolo"],
                        "name": "Luci Tavolo",
                        "nicknames": ["Luci Tavolo", "luci"],
                    },
                    "willReportState": False,
                    "attributes": {"pausable": False},
                },
            ],
        },
    }


def build_query_response(request_id, device_id_to_activity):
    """QUERY: device_id_to_activity maps requested device id -> activity string
    (one of ACTIVITY_VALUES) or None if the id is unknown/offline.

    Google's trait-schema validator expects every declared trait's state
    properties present regardless of online/offline status, so the offline
    branch still reports them (with the last-known/default "riposo" value)
    rather than a bare {"status": "OFFLINE"}."""
    states = {}
    for device_id, activity in device_id_to_activity.items():
        if activity is None:
            states[device_id] = {
                "status": "OFFLINE",
                "online": False,
                "currentModeSettings": {"activity": ACTIVITY_RIPOSO},
                "isRunning": False,
            }
            continue
        states[device_id] = {
            "status": "SUCCESS",
            "online": True,
            "currentModeSettings": {"activity": activity},
            "isRunning": activity != ACTIVITY_RIPOSO,
        }
    return {"requestId": request_id, "payload": {"devices": states}}


def build_execute_response(request_id, commands, skip_fn, get_activity_fn=None, next_pattern_fn=None):
    """EXECUTE: routes by device id.
      DEVICE_ID      + StartStop stop  → skip_fn()         ("salta questo disegno")
      DEVICE_ID_LUCE + StartStop start → next_pattern_fn() ("cambia effetto")
    """
    results = []
    for command_block in commands:
        device_ids = [d["id"] for d in command_block.get("devices", [])]
        for execution in command_block.get("execution", []):
            command = execution.get("command")
            params = execution.get("params", {})
            if command == "action.devices.commands.StartStop":
                is_luce = any(d == DEVICE_ID_LUCE for d in device_ids)
                if is_luce:
                    ok = next_pattern_fn() if next_pattern_fn else False
                    results.append({
                        "ids": device_ids,
                        "status": "SUCCESS" if ok else "ERROR",
                        **({"states": {"online": True, "isRunning": True}} if ok else
                           {"errorCode": "actionNotAvailable",
                            "debugString": "NanoLED non disponibile"}),
                    })
                elif params.get("start") is False:
                    ok, message = skip_fn()
                    if ok:
                        activity = get_activity_fn() if get_activity_fn else ACTIVITY_RIPOSO
                        results.append({
                            "ids": device_ids,
                            "status": "SUCCESS",
                            "states": {
                                "online": True,
                                "isRunning": activity != ACTIVITY_RIPOSO,
                                "currentModeSettings": {"activity": activity},
                            },
                        })
                    else:
                        results.append({
                            "ids": device_ids,
                            "status": "ERROR",
                            "errorCode": "actionNotAvailable",
                            "debugString": message,
                        })
                else:
                    results.append({
                        "ids": device_ids,
                        "status": "ERROR",
                        "errorCode": "functionNotSupported",
                        "debugString": "Unsupported command",
                    })
            else:
                results.append({
                    "ids": device_ids,
                    "status": "ERROR",
                    "errorCode": "functionNotSupported",
                    "debugString": "Unsupported command: {}".format(command),
                })
    return {"requestId": request_id, "payload": {"commands": results}}
