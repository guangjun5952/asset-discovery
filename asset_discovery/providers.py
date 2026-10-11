"""Bounded official API access; license-aware verification before download."""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from .core import clean_html, now, probe, sha, write_json, read_json

from .rights import CC0, cc_license, apply_policy
from .stock import stock_detail, stock_search, browser_task, credential
COMMONS = 'https://commons.wikimedia.org/w/api.php'
FREESOUND = 'https://freesound.org/apiv2/'


def is_cc0(url):
    if not isinstance(url, str):
        return False
    p = urllib.parse.urlsplit(url.strip())
    return (p.scheme in ('http', 'https') and p.netloc.lower() == 'creativecommons.org'
            and p.path.rstrip('/') == '/publicdomain/zero/1.0' and not p.query and not p.fragment)


def allowed_url(url):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ''
    return p.scheme == 'https' and p.port in (None, 443) and not p.username and not p.password and (
        host in ('commons.wikimedia.org', 'upload.wikimedia.org', 'freesound.org', 'pexels.com', 'pixabay.com') or
        any(host.endswith('.'+domain) for domain in ('freesound.org', 'pexels.com', 'pixabay.com')))


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError('Unexpected download redirect host; stopped')
        if urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query).get('key'):
            raise ValueError('API-key query redirects disabled')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header('Authorization')
        return redirected


class Network:
    def __init__(self, project):
        self.project = project
        self.settings = project.config['online']
        if not self.settings.get('enabled'):
            raise ValueError('Online access disabled in config')
        contact = self.settings.get('contact', '').strip()
        if not contact or any(c in contact for c in '\r\n'):
            raise ValueError('Set online.contact to your email, URL or Wikimedia username')
        self.ua = f'GuangjunAssetDiscoveryBot/0.2 ({contact})'
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.last = 0

    def open(self, url, headers=None):
        if not allowed_url(url):
            raise ValueError('Host is outside supported providers')
        for attempt in range(3):
            time.sleep(max(0, max(1.0, float(self.settings['request_interval']))-(time.monotonic()-self.last)))
            self.last = time.monotonic()
            try:
                return self.opener.open(urllib.request.Request(url, headers={'User-Agent': self.ua, **(headers or {})}), timeout=45)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 502, 503) or attempt == 2:
                    raise RuntimeError(f'Provider HTTP {e.code}; request stopped') from None
                delay = e.headers.get('Retry-After', '')
                if delay.isdigit() and int(delay) > 30:
                    raise RuntimeError('Provider asks for a longer pause; retry later') from None
                time.sleep(int(delay) if delay.isdigit() else 2**(attempt+1))
            except urllib.error.URLError:
                raise RuntimeError('Provider connection failed; URL and credentials omitted') from None

    def get(self, url, headers=None):
        # Pixabay explicitly requires 24h request caching; never store its key-bearing URL.
        parsed = urllib.parse.urlsplit(url)
        cached = None
        if parsed.hostname == 'pixabay.com' and parsed.path.startswith('/api/'):
            public_params = [(k,v) for k,v in urllib.parse.parse_qsl(parsed.query) if k != 'key']
            digest = hashlib.sha256(json.dumps([parsed.path, sorted(public_params)]).encode()).hexdigest()
            cached = self.project.path/'api-cache'/('pixabay-'+digest+'.json')
            if cached.exists() and time.time()-cached.stat().st_mtime < 86400:
                return read_json(cached)
        with self.open(url, headers) as r:
            data = r.read(10*1024*1024+1)
        if len(data) > 10*1024*1024:
            raise ValueError('Metadata response too large')
        result = json.loads(data)
        if 'error' in result:
            raise ValueError('Provider reported an API error')
        if cached is not None: write_json(cached, result)
        return result


def commons_record(page):
    info = page.get('imageinfo', [{}])[0]
    ext = info.get('extmetadata', {})
    value = lambda k: clean_html(ext.get(k, {}).get('value', ''))
    license_id = cc_license(value('LicenseUrl'))
    short = value('LicenseShortName').lower()
    if not license_id or (license_id=='cc0' and short not in ('cc0', 'cc0 1.0', 'cc-zero')):
        return None
    if license_id!='cc0' and short.replace(' ', '-').rstrip('-') != license_id:
        return None
    mime = info.get('mime', '')
    if not mime.startswith(('video/', 'audio/')):
        return None
    return {'provider': 'commons', 'id': page['title'], 'title': page['title'],
            'kind': 'video' if mime.startswith('video/') else 'audio', 'mime': mime,
            'license_url': value('LicenseUrl'), 'license_id': license_id, 'license_status': 'provider_metadata_verified',
            'source_page': info.get('descriptionurl'), 'download_url': info.get('url'),
            'author': value('Artist'), 'description': value('ImageDescription'),
            'restrictions': value('Restrictions'), 'checked_at': now(),
            'provider_sha1': info.get('sha1'), 'provider_size': info.get('size'),
            'variant': 'original', 'evidence': page}


def freesound_record(data):
    # Search labels are insufficient: accept only canonical per-item license URL.
    license_id = cc_license(data.get('license'))
    if not license_id:
        return None
    return {'provider': 'freesound', 'id': str(data['id']), 'title': data['name'],
            'kind': 'audio', 'license_url': data['license'], 'license_id': license_id, 'license_status': 'provider_metadata_verified',
            'source_page': data['url'], 'author': data.get('username', ''),
            'description': clean_html(data.get('description', '')), 'checked_at': now(),
            'download_url': data.get('previews', {}).get('preview-hq-mp3'),
            'variant': 'preview-hq-mp3', 'restrictions': '', 'evidence': data}


def fs_auth(project, original=False):
    online = project.config['online']
    use = online.get('freesound_api_use', 'unconfirmed')
    if use not in ('noncommercial', 'commercial_agreement'):
        raise ValueError('Confirm Freesound API eligibility in config; CC0 alone is insufficient')
    if use == 'commercial_agreement' and not online.get('freesound_agreement_reference'):
        raise ValueError('Commercial API use requires an agreement reference')
    env = 'FREESOUND_OAUTH_TOKEN' if original else 'FREESOUND_API_KEY'
    key = os.getenv(env)
    if not key:
        raise ValueError(f'Set {env}; credentials stay in environment')
    return {'Authorization': ('Bearer ' if original else 'Token ')+key}


def detail(project, provider, ident, network=None):
    net = network or Network(project)
    if provider == 'commons':
        if not ident.startswith('File:'):
            raise ValueError('Commons ID must be exact File: title')
        params = {'action': 'query', 'format': 'json', 'titles': ident, 'prop': 'imageinfo',
                  'iiprop': 'url|mime|size|sha1|extmetadata'}
        result = net.get(COMMONS+'?'+urllib.parse.urlencode(params))
        pages = list(result.get('query', {}).get('pages', {}).values())
        record = commons_record(pages[0]) if len(pages)==1 else None
    elif provider == 'freesound':
        if not str(ident).isdigit():
            raise ValueError('Freesound ID must be numeric')
        record = freesound_record(net.get(FREESOUND+f'sounds/{ident}/', fs_auth(project)))
    elif provider in ('pexels', 'pixabay'):
        record = stock_detail(project, provider, ident, net)
    else:
        raise ValueError('Use browser search and import-web for this provider')
    if not record:
        raise ValueError('No unambiguous recognized audio/video license on item metadata; rejected')
    return apply_policy(project, record)


def search_online(project, provider, query, kind='video', limit=5, browser=False):
    limit = max(1, min(int(limit), int(project.config['online']['max_results']), 20))
    if provider == 'mixkit' or (provider=='pixabay' and kind=='audio') or browser:
        if provider not in ('pexels', 'pixabay', 'mixkit'): raise ValueError('Browser adapter not provided for this source')
        return browser_task(provider, query, kind)
    net = Network(project)
    mode = project.config['online'].get('license_mode', 'commercial_edit')
    cache_key = hashlib.sha256(json.dumps([provider, query, kind, limit, mode, project.config['online'].get('intended_use', 'web_video'), project.config['online'].get('pixabay_editors_choice', False)]).encode()).hexdigest()
    cache = project.path/'online-cache'/f'{cache_key}.json'
    # Validate credentials / API eligibility even when serving a cached result.
    auth = fs_auth(project) if provider == 'freesound' else None
    if provider in ('pexels', 'pixabay'): credential(provider)
    if cache.exists() and time.time()-cache.stat().st_mtime < 86400:
        return dict(read_json(cache), cached=True)
    candidates, rejected = [], []
    if provider == 'commons':
        filetype = 'video' if kind=='video' else 'audio'
        params = {'action': 'query', 'format': 'json', 'list': 'search', 'srnamespace': 6,
                  'srsearch': f'{query} filetype:{filetype}' + (' incategory:"CC-Zero"' if mode=='strict_cc0' else ''), 'srlimit': limit}
        results = net.get(COMMONS+'?'+urllib.parse.urlencode(params)).get('query', {}).get('search', [])
        ids = [r['title'] for r in results]
    elif provider == 'freesound':
        if kind != 'audio':
            raise ValueError('Freesound provides audio only')
        params = {'query': query, 'filter': 'license:"Creative Commons 0"' if mode=='strict_cc0' else '(license:"Creative Commons 0" OR license:"Attribution")', 'page_size': limit, 'fields': 'id,name,license'}
        results = net.get(FREESOUND+'search/text/?'+urllib.parse.urlencode(params), auth)
        ids = [str(r['id']) for r in results.get('results', [])]
    elif provider in ('pexels', 'pixabay'):
        if kind != 'video': raise ValueError('This API adapter supports video only')
        records, rejected = stock_search(project, provider, query, limit, net)
        for record in records:
            try: candidates.append(apply_policy(project, record))
            except ValueError as e: rejected.append({'id': record['id'], 'reason': str(e)})
        ids = []
    else:
        raise ValueError('Unsupported provider')
    for ident in ids:
        try:
            candidates.append(detail(project, provider, ident, net))
        except ValueError as e:
            rejected.append({'id': ident, 'reason': str(e)})
    result = {'query': query, 'provider': provider, 'candidates': candidates, 'rejected': rejected,
              'checked_at': now(), 'cached': False, 'source_credit': f'Media provided by {provider}: ' + {'commons': 'https://commons.wikimedia.org/', 'freesound': 'https://freesound.org/', 'pexels': 'https://www.pexels.com/', 'pixabay': 'https://pixabay.com/'}[provider]}
    write_json(cache, result)
    return result


def download(project, provider, ident, original=False):
    net = Network(project)
    record = detail(project, provider, ident, net)  # Re-evaluate policy; Pixabay official detail cache must last 24h.
    headers = None
    if provider == 'freesound' and original:
        headers = fs_auth(project, original=True)
        url = FREESOUND+f'sounds/{ident}/download/'
        ext = '.'+record['evidence'].get('type', 'wav')
        record['variant'] = 'original'
    else:
        url = record['download_url']
        ext = Path(urllib.parse.urlsplit(url or '').path).suffix.lower()
    if not url or ext not in ('.mp4', '.webm', '.ogv', '.mov', '.ogg', '.mp3', '.wav', '.aiff', '.aif', '.flac', '.m4a', '.opus'):
        raise ValueError('Missing or unsupported original/preview media URL')
    folder = project.path/'downloads'
    folder.mkdir(exist_ok=True)
    ident_hash = hashlib.sha256((provider+ident+record['variant']).encode()).hexdigest()[:20]
    target = folder/(ident_hash+ext)
    provenance = Path(str(target)+'.license.json')
    if target.exists() and provenance.exists():
        previous = read_json(provenance)
        if (provider == 'commons' and record.get('provider_sha1') and
                previous.get('provider_sha1') == record['provider_sha1'] and
                previous.get('sha256') == sha(target)):
            write_json(provenance, dict(record, sha256=previous['sha256'], local_path=str(target)))
            return {'path': str(target), 'reused': True, 'license': record['license_url'], 'variant': record['variant']}
    temporary = target.with_suffix(ext+'.part')
    maximum = min(max(1, int(project.config['online']['max_download_mb'])), 1024)*1024*1024
    try:
        with net.open(url, headers) as response, temporary.open('wb') as out:
            if int(response.headers.get('Content-Length', '0')) > maximum:
                raise ValueError('Download exceeds configured size cap')
            size = 0
            while True:
                chunk = response.read(1024*1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise ValueError('Download exceeds configured size cap')
                out.write(chunk)
        probe(temporary)
        if provider == 'commons':
            expected = record.get('provider_sha1')
            if expected:
                h = hashlib.sha1()
                with temporary.open('rb') as f:
                    for chunk in iter(lambda: f.read(1024*1024), b''):
                        h.update(chunk)
                # MediaWiki versions may expose SHA1 in hex or base36.
                valid = h.hexdigest() == expected if len(expected)==40 else int(h.hexdigest(), 16)==int(expected, 36)
                if not valid:
                    raise ValueError('Provider SHA1 does not match downloaded original')
        digest = sha(temporary)
        temporary.replace(target)
        write_json(provenance, dict(record, sha256=digest, local_path=str(target)))
        write_json(str(target)+'.asset.json', {'description': record['description'], 'tags': [record['title']]})
        return {'path': str(target), 'sha256': digest, 'license': record['license_url'], 'variant': record['variant']}
    finally:
        temporary.unlink(missing_ok=True)
