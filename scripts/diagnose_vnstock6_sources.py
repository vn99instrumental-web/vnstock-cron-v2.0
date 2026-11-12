"""Read-only, secret-free capability diagnostic for Gen6 SSI and FHSC."""
from __future__ import annotations
import argparse, json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable
import vnstock
from vnstock import Fundamental, Market, Reference, sources
ROUTES=("reference.equity.list","market.equity.ohlcv","market.equity.quote","market.equity.trades","fundamental.equity.balance_sheet","fundamental.equity.income_statement","fundamental.equity.cash_flow")
def safe(value: Any) -> Any:
    if value is None or isinstance(value,(str,int,float,bool)): return value
    if isinstance(value,(list,tuple,set)): return [safe(item) for item in value]
    return str(value)
def summarize(call: Callable[[],Any]) -> dict[str,Any]:
    try:
        frame=call(); attrs=getattr(frame,"attrs",{})
        return {"status":"success","rows":int(len(frame)),"columns":sorted(str(c) for c in frame.columns),"source_used":safe(attrs.get("source_used")),"source_skipped":safe(attrs.get("source_skipped")),"schema_changes":safe(attrs.get("schema_changes",[]))}
    except Exception as exc:
        return {"status":"error","error_type":type(exc).__name__,"error_code":safe(getattr(exc,"code",None)),"error_action":safe(getattr(exc,"action",None))}
def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--output",required=True); args=parser.parse_args(); start=(date.today()-timedelta(days=45)).isoformat()
    readers={}
    for route in ROUTES:
        try: readers[route]=sorted(str(item) for item in sources.readers(route))
        except Exception as exc: readers[route]={"error_type":type(exc).__name__,"error_code":safe(getattr(exc,"code",None))}
    calls={"ssi.reference.equity.list":summarize(lambda:Reference("ssi").equity.list()),"ssi.market.equity.ohlcv":summarize(lambda:Market("ssi").equity("FPT").ohlcv(start=start)),"fhsc.market.equity.ohlcv":summarize(lambda:Market("fhsc").equity("FPT").ohlcv(start=start)),"fhsc.fundamental.equity.balance_sheet":summarize(lambda:Fundamental("fhsc").equity("FPT").balance_sheet()),"fhsc.fundamental.equity.income_statement":summarize(lambda:Fundamental("fhsc").equity("FPT").income_statement()),"fhsc.fundamental.equity.cash_flow":summarize(lambda:Fundamental("fhsc").equity("FPT").cash_flow())}
    payload={"schema_version":1,"package_version":str(vnstock.__version__),"sources":["ssi","fhsc"],"readers":readers,"calls":calls}; output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(payload,ensure_ascii=False))
if __name__=="__main__": main()