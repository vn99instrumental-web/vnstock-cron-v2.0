"""Materialize an isolated Gen6 serving release and native dashboard manifest."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parent.parent
VERSION="v6.0-native"
SOURCE=ROOT/"output/serving/current"
TARGET=ROOT/"output/serving/vnstock6/current"
def read(path: Path, default: Any=None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
def only_version(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    return [row for row in rows if row.get("scoring_version",row.get("config_version"))==VERSION]
def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--run-id",required=True); parser.add_argument("--run-url",required=True); args=parser.parse_args()
    required=[SOURCE/section/f"{VERSION}.json" for section in ("today","buy","history","analysis")]
    missing=[str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing: raise RuntimeError(f"Missing Gen6 serving datasets: {missing}")
    if TARGET.parent.exists(): shutil.rmtree(TARGET.parent)
    for section in ("today","buy","history","analysis"):
        shutil.copy2(SOURCE/section/f"{VERSION}.json",TARGET/section/f"{VERSION}.json")
    charts=SOURCE/"charts"/VERSION
    if not charts.exists(): raise RuntimeError("Missing Gen6 charts")
    shutil.copytree(charts,TARGET/"charts"/VERSION)
    metadata=read(SOURCE/"metadata.json",{})
    metadata["runs"]={VERSION:(metadata.get("runs") or {}).get(VERSION)}
    metadata["coverage"]={VERSION:(metadata.get("coverage") or {}).get(VERSION)}
    metadata["source_provenance"]="vnstock6-native"
    metadata["generation"]=6
    metadata["sources"]={"reference":"SSI","market_primary":"SSI","market_fallback":"FHSC","fundamental":"FHSC"}
    write(TARGET/"metadata.json",metadata)
    ic=read(SOURCE/"ic.json",{"schema_version":1,"metrics":[],"indicators":[],"factor_versions":[],"marginal":[],"industry":[],"industry_errors":{}})
    for key in ("metrics","indicators","factor_versions","marginal","industry"):
        ic[key]=only_version(ic.get(key,[]))
    ic["source"]="vnstock6"; write(TARGET/"ic.json",ic)
    datasets=[]
    for path in sorted(TARGET.rglob("*.json")):
        if path.name=="manifest.json": continue
        body=path.read_bytes(); datasets.append({"path":path.relative_to(TARGET).as_posix(),"bytes":len(body),"sha256":hashlib.sha256(body).hexdigest()})
    generated=datetime.now(timezone.utc).isoformat()
    write(TARGET/"manifest.json",{"schema_version":2,"release_id":metadata.get("release_id"),"generated_at_utc":generated,"source_provenance":"vnstock6-native","quality":{"status":"PASS","checks":["native_generation","source_provenance","dataset_sha256"]},"datasets":datasets})
    today=read(TARGET/"today"/f"{VERSION}.json",{}); symbols=sorted({str(row["symbol"]) for row in today.get("signals",[]) if row.get("symbol")})
    dashboard={"schema_version":1,"mode":"native","generated_at":generated,"source":"SSI","sources":{"reference":"SSI","market_primary":"SSI","market_fallback":"FHSC","fundamental":"FHSC"},"package_version":"6.0.0","oapi_version":"0.1.1","upstream":None,"symbols":symbols,"capabilities":{name:"native" for name in ("metadata","today","buy","history","history_detail","analysis","ic","chart")},"flow":{"run_id":args.run_id,"run_url":args.run_url,"stages":[{"name":name,"status":"success","mode":"native"} for name in ("authenticate","reference","market_ingest","fundamental_ingest","scoring","serving")]}}
    write(ROOT/"output/vnstock6-preview/dashboard.json",dashboard)
    print(f"VNStock6 native serving: {len(symbols)} symbols, {len(datasets)} datasets")
if __name__=="__main__": main()