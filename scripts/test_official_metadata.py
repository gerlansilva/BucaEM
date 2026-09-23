from official_metadata import parse_publisher_html, normalize_crossref

HTML=b'''<html><head>
<meta name="citation_title" content="Official article title">
<meta name="citation_author" content="Ana Silva">
<meta name="citation_author" content="John Doe">
<meta name="citation_journal_title" content="Journal of Mathematics Education">
<meta name="citation_doi" content="10.1234/example.1">
<meta name="citation_publication_date" content="2025/06/12">
<meta name="citation_volume" content="12"><meta name="citation_issue" content="2">
<meta name="citation_firstpage" content="101"><meta name="citation_lastpage" content="119">
<meta name="citation_abstract" content="Canonical abstract from publisher.">
<meta name="citation_keywords" content="probability; teacher education">
<meta name="citation_pdf_url" content="https://publisher.example/a.pdf">
<link rel="canonical" href="https://publisher.example/article/1">
</head></html>'''

def main():
    p=parse_publisher_html(HTML,'https://publisher.example/article/1')
    assert p['title']=='Official article title'
    assert p['authors']==['Ana Silva','John Doe']
    assert p['doi']=='10.1234/example.1'
    assert p['year']==2025 and p['volume']=='12' and p['issue']=='2' and p['pages']=='101-119'
    assert p['abstract']=='Canonical abstract from publisher.'
    assert p['keywords']==['probability','teacher education']
    c=normalize_crossref({'title':['Crossref title'],'DOI':'10.1234/x','author':[{'given':'Ana','family':'Silva'}],'container-title':['Journal X'],'issued':{'date-parts':[[2024,1,2]]},'volume':'4','issue':'1','page':'1-8'})
    assert c['title']=='Crossref title' and c['authors']==['Ana Silva'] and c['year']==2024
    print('official metadata tests: ok')

if __name__=='__main__': main()
