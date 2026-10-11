import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from asset_discovery.core import Project, write_json, read_json, run, sha
from asset_discovery.providers import Network, detail, download, search_online, allowed_url
from asset_discovery.rights import policy, PLATFORM_LICENSES
from asset_discovery.stock import stock_record, stock_detail, browser_task
from asset_discovery.web_import import import_web
from asset_discovery.media import index, import_reviews
from asset_discovery.planning import search, choose
from asset_discovery.exporting import export

PEXELS = {'id': 42, 'url': 'https://www.pexels.com/video/trees-42/', 'user': {'name':'Author'}, 'duration':4,
          'video_files':[{'id':7, 'file_type':'video/mp4', 'link':'https://videos.pexels.com/42.mp4', 'width':1920, 'height':1080},
                         {'id':8, 'file_type':'video/mp4', 'link':'https://videos.pexels.com/42-4k.mp4', 'width':3840, 'height':2160}]}
PIXABAY = {'id': 43, 'pageURL':'https://pixabay.com/videos/id-43/', 'user':'Creator', 'tags':'forest trees', 'duration':4,
           'videos':{'medium':{'url':'https://cdn.pixabay.com/43.mp4', 'width':1920, 'height':1080, 'size':1000000}}}

class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media=tempfile.TemporaryDirectory()
        cls.video=Path(cls.temp_media.name)/'video.mp4'
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x96:rate=30:duration=1','-c:v','libx264',cls.video])
    @classmethod
    def tearDownClass(cls): cls.temp_media.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.p=Project.init(self.root/'p')
        self.p.config['online'].update(enabled=True, contact='fixture-only-no-live-requests')
    def tearDown(self): self.p.db.close(); self.temp.cleanup()
    def record(self, ident):
        return {'license_id':ident, 'license_url':PLATFORM_LICENSES[ident][1]}
    def test_stock_policy_and_strict_optin(self):
        for name in ('pexels','pixabay','mixkit-video-free','mixkit-music-free','mixkit-sfx-free'):
            self.assertEqual(policy(self.p,self.record(name))['decision'],'accepted_for_editing_subject_to_terms')
        self.p.config['online']['license_mode']='strict_cc0'
        with self.assertRaises(ValueError): policy(self.p,self.record('pexels'))
    def test_ccby_attribution_and_restricted(self):
        by={'license_url':'https://creativecommons.org/licenses/by/4.0/','author':'A','source_page':'https://freesound.org/s/1/'}
        self.assertTrue(policy(self.p,by)['attribution_required'])
        with self.assertRaises(ValueError): policy(self.p,dict(by,author=''))
        for code in ('by-nc','by-nd','by-sa'):
            with self.assertRaises(ValueError): policy(self.p,dict(by,license_url=f'https://creativecommons.org/licenses/{code}/4.0/'))
        with self.assertRaises(ValueError): policy(self.p,self.record('mixkit-video-restricted'))
    def test_music_scope(self):
        self.p.config['online']['intended_use']='tv_broadcast'
        with self.assertRaises(ValueError): policy(self.p,self.record('mixkit-music-free'))
        self.assertTrue(policy(self.p,self.record('mixkit-sfx-free')))
    def test_label_url_mismatch(self):
        with self.assertRaises(ValueError): policy(self.p,{'license_id':'cc0','license_url':PLATFORM_LICENSES['pexels'][1]})
        with self.assertRaises(ValueError): policy(self.p,{'license_id':'pexels','license_url':'https://evil.test/license'})
    def test_pexels_resolution_choice(self):
        result=stock_record(self.p,'pexels',PEXELS)
        self.assertEqual(result['variant'],'7')
        self.assertEqual(result['license_id'],'pexels')
        self.assertNotIn('CC0',result['license_url'])
    def test_stock_api_search_and_credit(self):
        with patch.dict(os.environ,{'PEXELS_API_KEY':'secret-fixture'}), patch.object(Network,'get',return_value={'videos':[PEXELS]}) as get:
            r=search_online(self.p,'pexels','trees')
            self.assertEqual(len(r['candidates']),1)
            self.assertIn('https://www.pexels.com/',r['source_credit'])
            self.assertIn('/v1/videos/search?',get.call_args.args[0])
            self.assertEqual(get.call_args.args[1]['Authorization'],'secret-fixture')
            self.assertNotIn('secret-fixture',json.dumps(r))
    def test_pixabay_detail_and_id(self):
        with patch.dict(os.environ,{'PIXABAY_API_KEY':'secret-fixture'}), patch.object(Network,'get',return_value={'hits':[PIXABAY]}) as get:
            r=detail(self.p,'pixabay','43')
            self.assertEqual(r['license_id'],'pixabay')
            self.assertEqual(parse_qs(urlsplit(get.call_args.args[0]).query)['id'],['43'])
            with self.assertRaises(ValueError): detail(self.p,'pixabay','99')
    def test_pixabay_24h_cache_no_key_on_disk(self):
        response=io.BytesIO(json.dumps({'hits':[PIXABAY]}).encode())
        net=Network(self.p)
        with patch.object(net,'open',return_value=response) as opened:
            a=net.get('https://pixabay.com/api/videos/?key=SECRET&id=43')
            b=net.get('https://pixabay.com/api/videos/?key=SECRET&id=43')
            self.assertEqual(a,b); self.assertEqual(opened.call_count,1)
        for f in (self.p.path/'api-cache').glob('*'):
            self.assertNotIn('SECRET',f.read_text()); self.assertNotIn('SECRET',f.name)
    def test_browser_route_is_explicit_not_fake_results(self):
        for provider,kind in [('mixkit','video'),('mixkit','audio'),('pixabay','audio')]:
            r=search_online(self.p,provider,'ocean',kind)
            self.assertEqual(r['mode'],'browser_assisted'); self.assertEqual(r['candidates'],[])
            self.assertTrue(r['tasks'])
        self.assertEqual(search_online(self.p,'pexels','ocean',browser=True)['mode'],'browser_assisted')
    def test_credential_required_no_accidental_scrape(self):
        with patch.dict(os.environ,{},clear=True), patch.object(Network,'open') as opened:
            with self.assertRaises(ValueError): search_online(self.p,'pexels','ocean')
            opened.assert_not_called()
    def test_stock_download_preserves_license(self):
        response=io.BytesIO(self.video.read_bytes()); response.headers={}
        with patch.dict(os.environ,{'PEXELS_API_KEY':'fixture'}), patch.object(Network,'get',return_value=PEXELS), patch.object(Network,'open',return_value=response):
            r=download(self.p,'pexels','42')
            self.assertEqual(r['license'],PLATFORM_LICENSES['pexels'][1])
            self.assertEqual(read_json(r['path']+'.license.json')['license_id'],'pexels')
    def receipt(self, ident='mixkit-video-free'):
        evidence=self.root/'evidence.txt'; evidence.write_text('TEST FIXTURE: Selected file variant displays Mixkit Stock Video Free License')
        r={'provider':'mixkit','source_page':'https://mixkit.co/free-stock-video/example-42/',
           'title':'Test fixture','license_id':ident,'license_url':PLATFORM_LICENSES[ident][1],
           'reviewed':True,'license_observed_text':'Stock Video Free License','variant':'720p',
           'checked_at':'2026-10-09T00:00:00+00:00','sha256':sha(self.video),'evidence_file':str(evidence)}
        path=self.root/'receipt.json'; write_json(path,r); return path
    def test_web_import_and_source_route(self):
        result=import_web(self.p,self.video,self.receipt())
        record=read_json(result['path']+'.license.json')
        self.assertEqual(record['license_status'],'agent_or_user_page_review')
        self.assertTrue(Path(record['evidence_file']).exists())
        self.p.config.update(min_video_height=64,require_review=False)
        index(self.p,[result['path']])
        self.assertTrue(search(self.p,'Test fixture',source='online'))
        self.assertFalse(search(self.p,'Test fixture',source='local'))
    def test_receipt_rejects_hash_and_restricted(self):
        path=self.receipt(); r=read_json(path); r['sha256']='wrong'; write_json(path,r)
        with self.assertRaises(ValueError): import_web(self.p,self.video,path)
        with self.assertRaises(ValueError): import_web(self.p,self.video,self.receipt('mixkit-video-restricted'))
    def test_export_checks_current_policy_and_credits(self):
        result=import_web(self.p,self.video,self.receipt())
        self.p.config.update(min_video_height=64,width=160,height=96)
        index(self.p,[result['path']]); s=self.p.segments()[0]
        review={'description':'Pattern','tags':['pattern'],'aesthetic':0.5,'usability':0.9,'confidence':1,
                'reject':False,'synthetic':True,'has_people':False,'has_logos':False}
        path=self.root/'review.json';write_json(path,[{'id':s['id'],'sha256':s['sha256'],'review':review}]);import_reviews(self.p,path)
        plan={'needs':[{'id':'a','query':'pattern','kind':'video','route':'online_only','duration':0.5,'at':0}]}
        selection=choose(self.p,plan,[{'need_id':'a','segment_id':s['id'],'source_in':0,'score':1,'reason':'fixture'}])
        out=self.root/'export';export(self.p,selection,out)
        self.assertIn('mixkit', (out/'CREDITS.md').read_text())
        self.p.config['online']['license_mode']='strict_cc0'
        with self.assertRaises(ValueError): export(self.p,selection,self.root/'blocked')
    def test_cdn_domains_and_lookalikes(self):
        for url in ('https://videos.pexels.com/42.mp4','https://cdn.pixabay.com/43.mp4'): self.assertTrue(allowed_url(url))
        self.assertFalse(allowed_url('https://cdn.pixabay.com.evil.test/43.mp4'))

if __name__=='__main__': unittest.main()
