import unittest
import xml.etree.ElementTree as ET
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import harvest
from harvest import parse_record

class HarvestTests(unittest.TestCase):
    def test_metadata(self):
        xml = '''<record xmlns="http://www.openarchives.org/OAI/2.0/"><header><identifier>oai:test:1</identifier><datestamp>2025-01-01</datestamp></header><metadata><dc xmlns="x" xmlns:d="http://purl.org/dc/elements/1.1/"><d:title xml:lang="en">English</d:title><d:title xml:lang="pt-BR">Título real</d:title><d:creator>Ana Silva</d:creator><d:description xml:lang="pt-BR">Um resumo.</d:description><d:date>2024-05-01</d:date><d:identifier>https://doi.org/10.1234/teste</d:identifier><d:identifier>https://example.org/article/view/1</d:identifier><d:language>pt-BR</d:language><d:subject>Ensino; Estatística</d:subject></dc></metadata></record>'''
        a = parse_record(ET.fromstring(xml), {'id':'test','oai':'https://example.org/oai'}, '2026-01-01')
        self.assertEqual(a['title'], 'Título real')
        self.assertEqual(a['doi'], '10.1234/teste')
        self.assertEqual(a['language'], 'Português')
        self.assertEqual(a['year'], 2024)
        self.assertEqual(a['keywords'], ['Ensino','Estatística'])
        self.assertEqual(a['url'], 'https://example.org/article/view/1')
        self.assertIsNone(a['openAccess'])
        self.assertEqual(a['id'], parse_record(ET.fromstring(xml), {'id':'test','oai':'https://example.org/oai'}, 'other')['id'])

    def test_deleted(self):
        a = parse_record(ET.fromstring('<record xmlns="http://www.openarchives.org/OAI/2.0/"><header status="deleted"><identifier>1</identifier></header></record>'), {'id':'test'}, '')
        self.assertTrue(a['deleted'])

    def test_missing_identifier(self):
        self.assertIsNone(parse_record(ET.fromstring('<record/>'), {}, ''))

    def test_failed_source_preserves_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dist/data').mkdir(parents=True)
            catalog = {'demo': False, 'articles': [{'id':'kept','year':2024}]}
            (root / 'dist/data/articles.json').write_text(json.dumps(catalog))
            (root / 'dist/data/journals.json').write_text(json.dumps([{'id':'test','oai':'https://example.org/oai','enabled':True}]))
            (root / 'dist/data/status.json').write_text('{"journals":[]}')
            with patch.object(harvest, 'ROOT', root), patch('sys.argv',['harvest.py']), patch.object(harvest, 'get_xml', side_effect=RuntimeError('indisponível')):
                with self.assertRaises(SystemExit):
                    harvest.main()
            self.assertEqual(json.loads((root / 'dist/data/articles.json').read_text()), catalog)
            self.assertEqual(json.loads((root / 'dist/data/status.json').read_text())['journals'][0]['status'], 'error')

    def test_success_replaces_demo(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'dist/data').mkdir(parents=True)
            (root/'dist/data/articles.json').write_text('{"demo":true,"articles":[]}')
            (root/'dist/data/journals.json').write_text('[{"id":"test","oai":"https://example.org/oai","enabled":true}]')
            (root/'dist/data/status.json').write_text('{"journals":[]}')
            forms=ET.fromstring('<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListMetadataFormats><metadataFormat><metadataPrefix>oai_dc</metadataPrefix></metadataFormat></ListMetadataFormats></OAI-PMH>')
            records=ET.fromstring('<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords><record><header><identifier>r1</identifier></header><metadata><dc xmlns:d="http://purl.org/dc/elements/1.1/"><d:title>Teste real</d:title></dc></metadata></record></ListRecords></OAI-PMH>')
            responses=[(forms,b'formats'),(forms,b'formats'),(records,ET.tostring(records))]
            with patch.object(harvest,'ROOT',root),patch('sys.argv',['harvest.py']),patch.object(harvest,'get_xml',side_effect=responses):
                harvest.main()
            catalog=json.loads((root/'dist/data/articles.json').read_text())
            self.assertFalse(catalog['demo'])
            self.assertEqual(len(catalog['articles']),1)
            self.assertEqual(catalog['articles'][0]['title'],'Teste real')

if __name__ == '__main__':
    unittest.main()
