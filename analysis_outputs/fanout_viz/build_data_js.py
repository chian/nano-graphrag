"""Turn payload.json into data.js — the slide deck's only data dependency.

Adds the derived figures each slide leads with (the acquisition funnel, the
yield concentration, the strategy roster) so the page renders numbers it was
handed rather than numbers it recomputed.
"""

import json

FAM_SLOT = {
    "initial": 0,
    "catalog shift": 1,
    "target shift": 2,
    "broad review": 3,
    "term swap": 4,
}

payload = json.load(open("payload.json"))

for run in payload["runs"]:
    trace = run["trace"]
    lv = run["levels"]

    hits = sum(s["hits"] for s in run["searches"])
    accepted = sum(s["accepted"] for s in run["searches"])
    pages = lv.get("page", 0)
    dropped = sum(v for k, v in run["fates"].items() if k != "extracted")
    read = run["fates"].get("extracted", 0)
    yielded = sum(1 for t in trace if t["a"] > 0)
    attrs = sum(t["a"] for t in trace)

    ys = sorted((t["a"] for t in trace), reverse=True)
    total = sum(ys) or 1
    cum = 0
    p80 = 0
    for i, y in enumerate(ys, start=1):
        cum += y
        if cum >= 0.8 * total:
            p80 = i
            break

    run["funnel"] = {
        "hits": hits,
        "accepted": accepted,
        "pages": pages,
        "read": read,
        "dropped": dropped,
        "yielded": yielded,
        "attrs": attrs,
        "p80": p80,
        "probes": lv.get("lexical_probe", 0),
        "tables": lv.get("source_table", 0),
        "chunks": run["chunks"],
    }

    for s in run["searches"]:
        s["slot"] = FAM_SLOT.get(s["fam"], 0)

    fams = []
    for s in run["searches"]:
        if s["fam"] not in [f["name"] for f in fams]:
            fams.append({"name": s["fam"], "slot": s["slot"]})
    run["families"] = fams

with open("data.js", "w") as fh:
    fh.write("window.FANOUT=")
    json.dump(payload, fh, separators=(",", ":"))
    fh.write(";\n")

import os
print("data.js %.2f MB" % (os.path.getsize("data.js") / 1e6))
for r in payload["runs"]:
    f = r["funnel"]
    print("%-52s hits=%-5d acc=%-4d pages=%-5d read=%-4d yielded=%-4d attrs=%-5d p80=%d"
          % (r["run"], f["hits"], f["accepted"], f["pages"], f["read"], f["yielded"], f["attrs"], f["p80"]))
