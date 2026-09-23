import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scielo import parse_metadata, record_from_variants, is_probable_article
from catalog_merge import integrate_records

HTML_PT = b'''<html lang="pt-BR"><head>
<meta name="citation_title" content="Ensino de Probabilidade na Escola">
<meta name="citation_author" content="Ana Silva"><meta name="citation_author" content="Joao Souza">
<meta name="citation_publication_date" content="2025/03/01">
<meta name="citation_doi" content="10.1590/1980-4415v39a01">
<meta name="citation_pdf_url" content="https://www.scielo.br/pdf/x.pdf">
<meta name="citation_language" content="pt">
<meta name="DC.Description" content="Resumo em portugues.">
<meta name="DC.Subject" content="Probabilidade; Educacao Matematica">
</head></html>'''
HTML_EN = b'''<html lang="en"><head>
<meta name="citation_title" content="Ensino de Probabilidade na Escola">
<meta name="citation_author" content="Ana Silva"><meta name="citation_author" content="Joao Souza">
<meta name="citation_publication_date" content="2025/03/01">
<meta name="citation_doi" content="10.1590/1980-4415v39a01">
<meta name="citation_language" content="pt">
<meta name="DC.Description" content="Probability teaching at school.">
<meta name="DC.Subject" content="Probability; Mathematics Education">
</head></html>'''

class SciELOTest(unittest.TestCase):
    def test_metadata_and_no_false_english_title(self):
        pt = parse_metadata(HTML_PT, 'https://www.scielo.br/j/bolema/a/abc/')
        en = parse_metadata(HTML_EN, 'https://www.scielo.br/j/bolema/a/abc/?lang=en', 'en')
        pt['requestedLang']=''; en['requestedLang']='en'
        journal={'id':'bolema','scieloCode':'bolema'}
        row=record_from_variants(journal,'https://www.scielo.br/j/bolema/a/abc/',[pt,en],'2026-09-22T00:00:00+00:00')
        self.assertEqual(row['doi'],'10.1590/1980-4415v39a01')
        self.assertEqual(row['titleOriginal'],'Ensino de Probabilidade na Escola')
        self.assertEqual(row['titleEn'],'')
        self.assertEqual(row['abstractEn'],'Probability teaching at school.')
        self.assertIn('Probability', row['keywordsEn'])
        self.assertTrue(row['openAccess'])

    def test_front_matter_filter(self):
        self.assertFalse(is_probable_article({'title':'EDITORIAL','type':'Editorial'}))
        self.assertTrue(is_probable_article({'title':'Um estudo sobre algebra','type':'Article'}))

    def test_doi_merge_keeps_stable_id(self):
        records={'legacy':{'id':'legacy','journal':'bolema','doi':'10.1590/test','title':'A','titleOriginal':'A','year':2025,'source':'OAI','authors':['A'],'keywords':[]}}
        incoming=[{'id':'new','journal':'bolema','doi':'10.1590/test','title':'A','titleOriginal':'A','titleEn':'A study','year':2025,'source':'SciELO','authors':['A'],'keywords':[],'keywordsEn':[],'keywordsOriginal':[],'abstractEn':'English abstract','url':'https://scielo/x','pdf':'https://scielo/x.pdf','openAccess':True}]
        added, merged=integrate_records(records,incoming)
        self.assertEqual((added,merged),(0,1))
        self.assertIn('legacy', records)
        self.assertNotIn('new', records)
        self.assertEqual(records['legacy']['titleEn'],'A study')
        self.assertIn('SciELO',records['legacy']['source'])

if __name__=='__main__': unittest.main()
