#!/usr/bin/env python3
from __future__ import annotations
import json,re,ssl,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
UA="BuscaEM/5.0 (academic metadata harvester; https://github.com/gerlansilva/BucaEM)"

def load(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return d
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def request(url,timeout=20):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/xml,text/xml,*/*"})
    with urllib.request.urlopen(req,timeout=timeout,context=ssl.create_default_context()) as r:return r.read(),r.geturl()
def candidates(j):
    out=[]
    for k in ("oai","oaiBase","oaiUrl","oai_url"):
        if j.get(k):out.append(j[k])
    url=j.get("url") or ""
    if url:
        p=urllib.parse.urlsplit(url);base=f"{p.scheme or 'https'}://{p.netloc}";path=p.path.rstrip("/")
        if path:out.append(base+path+"/oai")
        m=re.search(r"(/index\.php/[^/]+)",path)
        if m:out.append(base+m.group(1)+"/oai")
        out += [base+"/oai",base+"/index.php/index/oai"]
    seen=set();return [x.rstrip("/") for x in out if x and not (x.rstrip("/") in seen or seen.add(x.rstrip("/")))]
def identify(base):
    raw,final=request(base+("&" if "?" in base else "?")+"verb=Identify")
    if b"OAI-PMH" not in raw:return None
    root=ET.fromstring(raw)
    def first(name):
        for e in root.iter():
            if e.tag.split("}")[-1]==name and e.text:return e.text.strip()
        return ""
    return {"baseUrl":first("baseURL") or base,"repositoryName":first("repositoryName"),"protocolVersion":first("protocolVersion"),"identifyUrl":final}
def main():
    journals=load(ROOT/"dist/data/journals.json",[])
    crossref=load(ROOT/"harvest/source_registry.json",{})
    report={"generatedAt":datetime.now(timezone.utc).isoformat(),"summary":{},"journals":{}}
    registry={};counts={"oai":0,"scielo":0,"crossref":0,"unresolved":0}
    for i,j in enumerate(journals,1):
        jid=j["id"];row={"id":jid,"name":j.get("name"),"url":j.get("url"),"country":j.get("country"),
        "scielo":bool(j.get("scieloCode")),"crossref":bool((crossref.get(jid) or {}).get("issn")),"oai":None,"strategy":[]}
        if row["scielo"]:counts["scielo"]+=1;row["strategy"].append("scielo")
        found=None
        for c in candidates(j):
            try:found=identify(c)
            except Exception:found=None
            if found:break
            time.sleep(.05)
        if found:
            row["oai"]=found;counts["oai"]+=1;row["strategy"].append("oai-pmh")
            registry[jid]={"baseUrl":found["baseUrl"].rstrip("/"),"metadataPrefix":"oai_dc","repositoryName":found["repositoryName"],"enabled":True}
        if row["crossref"]:counts["crossref"]+=1;row["strategy"].append("crossref")
        if not row["strategy"]:counts["unresolved"]+=1;row["strategy"].append("custom")
        report["journals"][jid]=row;print(f"[{i}/{len(journals)}] {jid}: {', '.join(row['strategy'])}")
    report["summary"]=counts;save(ROOT/"harvest/SOURCE_AUDIT.json",report);save(ROOT/"harvest/ojs_registry.json",registry)
if __name__=="__main__":main()
