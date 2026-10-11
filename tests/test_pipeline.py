import copy
import io
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
from asset_discovery.core import Project, probe, run, sha, write_json, read_json
from asset_discovery.media import bounds, index, import_reviews, validate_review
from asset_discovery.providers import is_cc0, allowed_url, commons_record, freesound_record, fs_auth, download, CC0
from asset_discovery.intelligence import AI, describe, embed, transcribe
from asset_discovery.planning import plan_script, validate_plan, search, assemble, choose
from asset_discovery.exporting import export, review_packet


def review(**changes):
    return {'description': '彩色动态图案 colorful moving test pattern', 'tags': ['彩色', 'pattern'],
            'aesthetic': 0.8, 'usability': 0.9, 'confidence': 0.95, 'reject': False,
            'synthetic': True, 'has_people': False, 'has_logos': False, **changes}


def need(**changes):
    return {'id': 'shot-001', 'query': '彩色 pattern', 'kind': 'video', 'route': 'local_only',
            'duration': 0.5, 'at': 0, 'real_only': False, **changes}


class PureTests(unittest.TestCase):
    def test_exact_cc0(self):
        for v in (CC0, CC0.replace('https:', 'http:'), CC0.rstrip('/')):
            self.assertTrue(is_cc0(v))
        for v in (None, 'CC0', 'https://creativecommons.org/licenses/by/4.0/', 'https://creativecommons.org/publicdomain/mark/1.0/',
                  'https://creativecommons.org.evil/publicdomain/zero/1.0/', CC0+'?x=1', 'https://evil/'+CC0,
                  'https://user@creativecommons.org/publicdomain/zero/1.0/'):
            self.assertFalse(is_cc0(v))

    def test_host_boundary(self):
        self.assertTrue(allowed_url('https://upload.wikimedia.org/a.webm'))
        self.assertTrue(allowed_url('https://cdn.freesound.org/previews/1.mp3'))
        for url in ('http://freesound.org/x', 'https://freesound.org.evil/x', 'https://127.0.0.1/x',
                    'https://freesound.org:8443/x', 'https://user:pass@freesound.org/x'):
            self.assertFalse(allowed_url(url))

    def test_scene_coverage(self):
        spans = bounds(20, [1, 1.1, 8, 8, 19.99], 4)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], 20)
        self.assertTrue(all(0 < b-a <= 4 for a,b in spans))
        self.assertTrue(all(a[1] == b[0] for a,b in zip(spans, spans[1:])))
        with self.assertRaises(ValueError): bounds(10, [], 0)

    def test_license_not_search_category(self):
        page = {'title': 'File:Test.webm', 'imageinfo': [{'mime': 'video/webm', 'extmetadata': {
            'LicenseShortName': {'value': 'CC0'}, 'LicenseUrl': {'value': CC0}}}]}
        self.assertIsNotNone(commons_record(page))
        page['imageinfo'][0]['extmetadata']['LicenseUrl']['value'] = 'https://creativecommons.org/licenses/by/4.0/'
        self.assertIsNone(commons_record(page))
        self.assertIsNone(freesound_record({'id': 1, 'license': 'Creative Commons 0'}))

    def test_review_schema(self):
        for change in ({'confidence': float('nan')}, {'aesthetic': 2}, {'reject': 'false'}, {'description': ''}, {'tags': [1]}):
            with self.assertRaises(ValueError): validate_review(review(**change))

    def test_plan_validation(self):
        for change in ({'id': '../escape'}, {'duration': 0}, {'duration': float('nan')}, {'route': 'generate'}, {'at': -1}):
            with self.assertRaises(ValueError): validate_plan({'needs': [need(**change)]})
        with self.assertRaises(ValueError): validate_plan({'needs': [need(), need()]})


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory()
        cls.video = Path(cls.base.name)/'source with spaces 彩色.mp4'
        cls.audio = Path(cls.base.name)/'tone.wav'
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=24:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', cls.video])
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', cls.audio])

    @classmethod
    def tearDownClass(cls): cls.base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.p = Project.init(self.root/'project')
        self.p.config.update(min_video_height=64, width=160, height=96, max_segment_seconds=2)
        write_json(self.p.path/'config.json', self.p.config)
        index(self.p, [self.video, self.audio])

    def tearDown(self):
        self.p.db.close()
        self.temp.cleanup()

    def reviewed(self):
        data = [{'id': s['id'], 'sha256': s['sha256'], 'review': review(description='tone sine 音效' if s['asset']['kind']=='audio' else '彩色 moving pattern')}
                for s in self.p.segments()]
        path = self.root/'reviews.json'
        write_json(path, data)
        import_reviews(self.p, path)

    def test_incremental(self):
        self.assertEqual(index(self.p, [self.video])['unchanged'], 1)
        self.assertEqual(len(self.p.segments()), 2)

    def test_unreviewed_not_auto_selected(self):
        result = assemble(self.p, {'needs': [need()]})
        self.assertEqual(len(result['unresolved']), 1)
        self.assertEqual(result['selections'], [])
        self.assertFalse(search(self.p, '彩色')[0]['eligible'])

    def test_review_hash_atomic(self):
        s = self.p.segments()[0]
        path = self.root/'bad.json'
        write_json(path, [{'id': s['id'], 'sha256': 'wrong', 'review': review()}])
        with self.assertRaises(ValueError): import_reviews(self.p, path)
        self.assertIsNone(self.p.segments()[0]['review'])

    def test_filters_and_real_only(self):
        self.reviewed()
        self.assertTrue(search(self.p, '彩色 pattern', duration=1))
        self.assertFalse(search(self.p, '彩色', duration=5))
        self.assertFalse(search(self.p, '彩色', real_only=True))
        self.assertFalse(search(self.p, '彩色', avoid=['pattern']))
        self.assertFalse(search(self.p, '彩色', must=['nonexistent']))
        self.assertFalse(search(self.p, '彩色', source='online'))

    def test_local_route_no_substitution_and_no_duplicates(self):
        self.reviewed()
        result = assemble(self.p, {'needs': [need(), need(id='shot-002', at=1)]})
        self.assertEqual(len(result['selections']), 1)
        self.assertEqual(len(result['unresolved']), 1)
        self.assertFalse(assemble(self.p, {'needs': [need(route='online_only') ]})['selections'])

    def test_export_actual_media_and_xml(self):
        self.reviewed()
        plan = {'needs': [need(), need(id='audio-001', kind='audio', query='tone', at=0.2)]}
        result = assemble(self.p, plan)
        out = self.root/'delivery with spaces'
        export(self.p, result, out)
        manifest = read_json(out/'manifest.json')
        self.assertEqual(len(manifest['clips']), 2)
        self.assertEqual(manifest['durationInFrames'], 21)
        self.assertEqual(len(ET.parse(out/'resolve.xml').findall('.//clipitem')), 3)
        for c in manifest['clips']:
            self.assertTrue(Path(c['absolutePath']).exists())
            info = probe(c['absolutePath'])
            self.assertAlmostEqual(info['duration'], 0.5, delta=0.05)
            run(['ffmpeg', '-v', 'error', '-i', c['absolutePath'], '-f', 'null', '-'])
        with self.assertRaises(ValueError): export(self.p, result, out)

    def test_source_integrity_blocks_export(self):
        self.reviewed()
        result = assemble(self.p, {'needs': [need()]})
        result['selections'][0]['sha256'] = 'changed'
        with self.assertRaises(ValueError): export(self.p, result, self.root/'out')
        self.assertFalse((self.root/'out').exists())

    def test_partial_and_invalid_timecodes(self):
        self.reviewed()
        result = assemble(self.p, {'needs': [need(), need(id='missing', query='zzzz')]})
        with self.assertRaises(ValueError): export(self.p, result, self.root/'out')
        result['unresolved'] = []
        result['selections'][0]['source_out'] = 999
        with self.assertRaises(ValueError): export(self.p, result, self.root/'out')

    def test_plan_routes_and_audio(self):
        result = plan_script(self.p, '我的录屏操作演示。城市街道行人。音效：键盘敲击。')
        self.assertEqual([n['route'] for n in result['needs']], ['local_only', 'local_first', 'local_first'])
        self.assertEqual(result['needs'][-1]['kind'], 'audio')

    def test_cloud_optin(self):
        self.p.config['ai']['base_url'] = 'https://some-provider.example/v1'
        with self.assertRaises(ValueError): AI(self.p)
        self.p.config['ai']['allow_remote_upload'] = True
        AI(self.p)
        self.p.config['ai']['base_url'] = 'http://some-provider.example/v1'
        with self.assertRaises(ValueError): AI(self.p)

    def test_ai_describe_contract_not_quality(self):
        self.p.config['ai']['model'] = 'fixture-model'
        with patch.object(AI, 'chat', return_value=review()) as chat:
            result = describe(self.p)
            self.assertEqual(result['reviewed'], 1)
            self.assertEqual(result['skipped_audio_without_audio_model'], 1)
            self.assertEqual(len([x for x in chat.call_args.args[1] if x['type']=='image_url']), 3)
        self.assertTrue(search(self.p, '彩色')[0]['eligible'])

    def test_embedding_identity_and_rerank(self):
        self.reviewed()
        self.p.config['ai']['embedding_model'] = 'fixture-embed'
        with patch.object(AI, 'embedding', return_value=[0.6, 0.8]):
            self.assertEqual(embed(self.p)['embedded'], 2)
            self.assertEqual(embed(self.p)['embedded'], 0)
            result = search(self.p, 'unrelated query', use_embeddings=True)
            self.assertEqual(result[0]['retrieval_method'], 'hybrid_text_and_embedding')
        self.p.config['ai']['embedding_model'] = 'other'
        with patch.object(AI, 'embedding', return_value=[0.6, 0.8]):
            self.assertFalse(search(self.p, 'unrelated query', use_embeddings=True))

    def test_asr_contract(self):
        self.p.config['ai']['transcription_model'] = 'fixture-asr'
        with patch.object(AI, 'request', return_value={'text': 'hello'}):
            self.assertEqual(transcribe(self.p)['transcribed_segments'], 1)
        self.assertTrue(any(s['transcript']=='hello' for s in self.p.segments()))

    def test_freesound_commercial_gate(self):
        with self.assertRaises(ValueError): fs_auth(self.p)
        self.p.config['online']['freesound_api_use'] = 'commercial_agreement'
        with self.assertRaises(ValueError): fs_auth(self.p)
        self.p.config['online']['freesound_agreement_reference'] = 'user-supplied-contract-ref'
        with patch.dict(os.environ, {'FREESOUND_API_KEY': 'fixture-key'}):
            self.assertEqual(fs_auth(self.p)['Authorization'], 'Token fixture-key')

    def test_download_reverifies_before_media(self):
        self.p.config['online'].update(enabled=True, contact='unit-test-no-network')
        with patch('asset_discovery.providers.Network.open') as opened, patch('asset_discovery.providers.detail', side_effect=ValueError('license changed')):
            with self.assertRaises(ValueError): download(self.p, 'commons', 'File:Something.webm')
            opened.assert_not_called()

    def test_invalid_download_cleans_partial(self):
        self.p.config['online'].update(enabled=True, contact='unit-test-no-network')
        fake = io.BytesIO(b'not video')
        fake.headers = {}
        record = {'download_url': 'https://upload.wikimedia.org/test.webm', 'variant': 'original'}
        with patch('asset_discovery.providers.detail', return_value=record), patch('asset_discovery.providers.Network.open', return_value=fake):
            with self.assertRaises(RuntimeError): download(self.p, 'commons', 'File:test.webm')
        self.assertFalse(list((self.p.path/'downloads').glob('*')))

    def test_agent_semantic_choice_and_interior_range(self):
        self.reviewed()
        segment = next(s for s in self.p.segments() if s['asset']['kind']=='video')
        plan = {'needs': [need(query='A visual metaphor unrelated to filename')]}
        decision = {'need_id': 'shot-001', 'segment_id': segment['id'], 'source_in': 0.7,
                    'score': 0.9, 'reason': 'Agent reviewed frames and found an appropriate visual pattern'}
        result = choose(self.p, plan, [decision])
        self.assertEqual(result['status'], 'ready')
        self.assertAlmostEqual(result['selections'][0]['source_out'], 1.2)
        for change in ({'source_in': -1}, {'source_in': 1.9}, {'score': float('nan')}, {'reason': ''}):
            with self.assertRaises(ValueError): choose(self.p, plan, [dict(decision, **change)])
        with self.assertRaises(ValueError): choose(self.p, {'needs': [need(real_only=True)]}, [decision])
        with self.assertRaises(ValueError): choose(self.p, {'needs': [need(route='online_only')]}, [decision])

    def test_download_validates_and_saves_evidence(self):
        import hashlib
        self.p.config['online'].update(enabled=True, contact='unit-test-no-network')
        data = self.video.read_bytes()
        response = io.BytesIO(data); response.headers = {'Content-Length': str(len(data))}
        record = {'provider': 'commons', 'id': 'File:test.mp4', 'license_url': CC0,
                  'download_url': 'https://upload.wikimedia.org/test.mp4', 'variant': 'original',
                  'provider_sha1': hashlib.sha1(data).hexdigest(), 'description': 'test', 'title': 'test'}
        with patch('asset_discovery.providers.detail', return_value=record), patch('asset_discovery.providers.Network.open', return_value=response):
            result = download(self.p, 'commons', 'File:test.mp4')
        self.assertEqual(result['sha256'], sha(self.video))
        evidence = read_json(result['path']+'.license.json')
        self.assertEqual(evidence['license_url'], CC0)
        self.assertEqual(probe(result['path'])['kind'], 'video')

    def test_download_size_cap(self):
        self.p.config['online'].update(enabled=True, contact='unit-test-no-network', max_download_mb=1)
        response = io.BytesIO(b''); response.headers = {'Content-Length': str(2*1024*1024)}
        record = {'download_url': 'https://upload.wikimedia.org/test.mp4', 'variant': 'original'}
        with patch('asset_discovery.providers.detail', return_value=record), patch('asset_discovery.providers.Network.open', return_value=response):
            with self.assertRaises(ValueError): download(self.p, 'commons', 'File:test.mp4')
        self.assertFalse(list((self.p.path/'downloads').glob('*')))

    def test_changed_invalid_source_removes_stale_index(self):
        copied = self.root/'copy.mp4'; copied.write_bytes(self.video.read_bytes())
        index(self.p, [copied])
        self.assertEqual(len(self.p.segments()), 3)
        copied.write_bytes(b'invalid')
        result = index(self.p, [copied])
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(len(self.p.segments()), 2)

    def test_review_packet_has_playable_sources(self):
        result = review_packet(self.p, self.root/'review')
        self.assertEqual(result['segments'], 2)
        for entry in read_json(result['packet']):
            self.assertGreater(probe(entry['preview'])['duration'], 0)
            self.assertEqual(entry['sha256'], sha(entry['source_path']))


if __name__=='__main__': unittest.main()
