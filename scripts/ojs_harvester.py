#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,re,ssl,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];UA="BuscaEM/5.0 (academic metadata harvester)"

def load(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return d
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");t.replace(p)
def req(url):
    q=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/xml,text/xml,*/*"})
    with urllib.request.urlopen(q,timeout=90,context=ssl.create_default_context()) as r:return r.read()
def c(x):return re.sub(r"\s+"," ",str(x or "")).strip()
def lang(e):return (e.attrib.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower().replace("_","-").split("-")[0]
def vals(md,n):return [(c(e.text),lang(e)) for e in md.iter() if e.tag.split("}")[-1].lower()==n and c(e.text)]
def choose(vs,l):
    for t,x in vs:
        if x==l:return t
    return vs[0][0] if vs else ""
def splitkw(vs,l):
    out=[]
    for t,x in vs:
        if x==l or (not l and not x):
            for k in re.split(r"\s*[;|]\s*",t):
                k=c(k)
                if k and k.casefold() not in [z.casefold() for z in out]:out.append(k)
    return out
def norm(rec,jid):
    header=next((x for x in rec if x.tag.split("}")[-1]=="header"),None)
    if header is not None and header.attrib.get("status")=="deleted":return None
    oid="";stamp=""
    if header is not None:
        for e in header:
            if e.tag.split("}")[-1]=="identifier":oid=c(e.text)
            elif e.tag.split("}")[-1]=="datestamp":stamp=c(e.text)
    wrap=next((x for x in rec if x.tag.split("}")[-1]=="metadata"),None)
    if wrap is None or not list(wrap):return None
    md=list(wrap)[0];titles=vals(md,"title");descs=vals(md,"description");subs=vals(md,"subject")
    authors=[x[0] for x in vals(md,"creator")];ids=[x[0] for x in vals(md,"identifier")]
    ls=[x[0].lower() for x in vals(md,"language")];types=[x[0] for x in vals(md,"type")];dates=[x[0] for x in vals(md,"date")]
    lc=""
    for x in ls:
        if x.startswith("en"):lc="en";break
        if x.startswith("pt"):lc="pt"
        elif x.startswith("es") and not lc:lc="es"
    if not lc:
        for _,x in titles:
            if x:lc=x;break
    to=choose(titles,lc);te=choose(titles,"en") if any(x=="en" for _,x in titles) else ""
    ao=choose(descs,lc);ae=choose(descs,"en") if any(x=="en" for _,x in descs) else ""
    ko=splitkw(subs,lc);ke=splitkw(subs,"en");doi="";url=""
    for x in ids:
        m=re.search(r"10\.\d{4,9}/\S+",x,re.I)
        if m and not doi:doi=m.group(0).rstrip(".,;)")
        if x.startswith("http") and not url:url=x
    year=0
    for d in dates+[stamp]:
        m=re.search(r"\b(?:19|20)\d{2}\b",d or "")
        if m:year=int(m.group());break
    key=doi.lower() if doi else oid or f"{to}|{year}"
    rid=hashlib.sha256(f"{jid}|oai|{key}".encode()).hexdigest()[:24]
    return {"id":rid,"journal":jid,"title":to,"titleOriginal":to,"titleEn":te,"titles":[x[0] for x in titles],
    "titleVariants":[{"text":t,"lang":l} for t,l in titles],"authors":authors,"institutions":[],
    "abstract":ao,"abstractOriginal":ao,"abstractEn":ae,"abstracts":[x[0] for x in descs],
    "abstractVariants":[{"text":t,"lang":l} for t,l in descs],"keywords":ko,"keywordsOriginal":ko,"keywordsEn":ke,
    "keywordVariants":[{"text":t,"lang":l} for t,l in subs],"metadataEnglishStatus":"source" if (te or ae or ke or lc=="en") else "pending_translation",
    "year":year,"language":{"en":"English","pt":"Portuguese","es":"Spanish"}.get(lc,lc),"languageCode":lc,
    "type":types[0] if types else "article","doi":doi,"url":url,"pdf":"","openAccess":None,"oaiIdentifier":oid,
    "source":"OAI-PMH / OJS","provenance":["OAI-PMH / OJS"],"harvestedAt":datetime.now(timezone.utc).isoformat()}
def listurl(base,prefix,token):
    p={"verb":"ListRecords","resumptionToken":token} if token else {"verb":"ListRecords","metadataPrefix":prefix}
    return base+"?"+urllib.parse.urlencode(p)
def one(jid,cfg,records,state,max_pages):
    st=state.setdefault(jid,{});token=st.get("resumptionToken","");page=int(st.get("pages",0));done=False;npage=0
    while True:
        if max_pages and npage>=max_pages:break
        raw=req(listurl(cfg["baseUrl"],cfg.get("metadataPrefix","oai_dc"),token))
        d=ROOT/"harvest/raw"/jid/"oai";d.mkdir(parents=True,exist_ok=True)
        (d/f"{page:06d}-{hashlib.sha256(raw).hexdigest()[:16]}.xml").write_bytes(raw)
        root=ET.fromstring(raw);lr=next((e for e in root.iter() if e.tag.split("}")[-1]=="ListRecords"),None)
        if lr is None:raise RuntimeError("No ListRecords")
        count=0;next_token=""
        for e in lr:
            local=e.tag.split("}")[-1]
            if local=="record":
                r=norm(e,jid)
                if r:records[r["id"]]=r;count+=1
            elif local=="resumptionToken":next_token=c(e.text)
        page+=1;npage+=1;st.update({"pages":page,"recordsSeen":st.get("recordsSeen",0)+count,"resumptionToken":next_token,
        "lastRun":datetime.now(timezone.utc).isoformat(),"complete":False})
        save(ROOT/"harvest/ojs_state.json",state);save(ROOT/"harvest/ojs_catalog.json",{"articles":list(records.values())})
        if not next_token:done=True;break
        token=next_token
    st["complete"]=done
    if done:st["completedAt"]=datetime.now(timezone.utc).isoformat()
    return {"id":jid,"method":"oai-pmh","complete":done,"pagesThisRun":npage,"recordsSeen":st.get("recordsSeen",0),"baseUrl":cfg["baseUrl"]}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--journal");ap.add_argument("--max-pages",type=int,default=0);a=ap.parse_args()
    reg=load(ROOT/"harvest/ojs_registry.json",{});wanted=set(a.journal.split(",")) if a.journal else None
    state=load(ROOT/"harvest/ojs_state.json",{});cat=load(ROOT/"harvest/ojs_catalog.json",{"articles":[]})
    records={x["id"]:x for x in cat.get("articles",[]) if x.get("id")};status=load(ROOT/"harvest/OJS_STATUS.json",{"generatedAt":"","journals":{}})
    for jid,cfg in reg.items():
        if not cfg.get("enabled",True) or (wanted and jid not in wanted):continue
        try:rep=one(jid,cfg,records,state,a.max_pages)
        except Exception as e:rep={"id":jid,"method":"oai-pmh","complete":False,"error":str(e)}
        status["journals"][jid]=rep;status["generatedAt"]=datetime.now(timezone.utc).isoformat();save(ROOT/"harvest/OJS_STATUS.json",status);print(json.dumps(rep,ensure_ascii=False))
    save(ROOT/"harvest/ojs_state.json",state);save(ROOT/"harvest/ojs_catalog.json",{"articles":list(records.values())})
if __name__=="__main__":main()
