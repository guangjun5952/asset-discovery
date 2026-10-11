"""Pexels/Pixabay official video API adapters; Mixkit and audio web handoff."""
import os
from urllib.parse import urlencode, urlsplit
from .core import now, clean_html
from .rights import PLATFORM_LICENSES

PEXELS = 'https://api.pexels.com/v1/videos/'
PIXABAY = 'https://pixabay.com/api/videos/'


def credential(provider):
    name = {'pexels': 'PEXELS_API_KEY', 'pixabay': 'PIXABAY_API_KEY'}[provider]
    value = os.environ.get(name)
    if not value: raise ValueError(f'Set {name} or use online-search --browser')
    return value


def pick_variant(project, variants):
    variants = [v for v in variants if v.get('url') and v.get('width', 0) > 0 and v.get('height', 0) > 0]
    if not variants: raise ValueError('No usable video rendition')
    cap = project.config['online']['max_download_mb'] * 1024 * 1024
    variants = [v for v in variants if not v.get('size') or v['size'] <= cap]
    if not variants: raise ValueError('All video renditions exceed the download cap')
    area = project.config['width'] * project.config['height']
    return min(variants, key=lambda v: abs(v['width']*v['height']-area))


def stock_record(project, provider, data):
    if provider == 'pexels':
        variants = [dict(v, url=v.get('link'), name=str(v.get('id', 'mp4'))) for v in data.get('video_files', []) if v.get('file_type')=='video/mp4']
        author = data.get('user', {}).get('name', '')
        page = data.get('url', '')
        title = urlsplit(page).path.strip('/').split('/')[-1]
        description = title.replace('-', ' ')
    else:
        variants = [dict(v, name=k) for k,v in data.get('videos', {}).items() if v]
        author, page = data.get('user', ''), data.get('pageURL', '')
        title = description = data.get('tags', str(data['id']))
    v = pick_variant(project, variants)
    label, license_url = PLATFORM_LICENSES[provider]
    return {'provider': provider, 'id': str(data['id']), 'title': title, 'description': clean_html(description),
            'kind': 'video', 'license_id': provider, 'license_name': label, 'license_url': license_url,
            'license_status': 'official_api_item_under_provider_terms', 'source_page': page, 'author': author,
            'download_url': v['url'], 'variant': v['name'], 'width': v['width'], 'height': v['height'],
            'duration': data.get('duration'), 'checked_at': now(), 'terms_reviewed_on': '2026-10-09',
            'restrictions': 'Use within edited works; do not redistribute standalone stock or build competing libraries.',
            'evidence': data}


def stock_detail(project, provider, ident, net):
    if not str(ident).isdigit(): raise ValueError('Stock video ID must be numeric')
    key = credential(provider)
    if provider == 'pexels':
        data = net.get(PEXELS+str(ident), {'Authorization': key})
    else:
        response = net.get(PIXABAY+'?'+urlencode({'key': key, 'id': ident}))
        rows = [h for h in response.get('hits', []) if str(h['id'])==str(ident)]
        if len(rows)!=1: raise ValueError('Video ID not returned by official API')
        data = rows[0]
    if str(data['id']) != str(ident): raise ValueError('Provider item ID mismatch')
    return stock_record(project, provider, data)


def stock_search(project, provider, query, limit, net):
    key = credential(provider)
    if provider == 'pexels':
        params = {'query': query, 'per_page': limit, 'locale': 'zh-CN' if any('\u4e00'<=c<='\u9fff' for c in query) else 'en-US'}
        data = net.get(PEXELS+'search?'+urlencode(params), {'Authorization': key})
        hits = data.get('videos', [])
    else:
        params = {'key': key, 'q': query[:100], 'per_page': max(3, limit), 'safesearch': 'true',
                  'lang': 'zh' if any('\u4e00'<=c<='\u9fff' for c in query) else 'en',
                  'order': 'popular', 'editors_choice': str(project.config['online'].get('pixabay_editors_choice', False)).lower()}
        hits = net.get(PIXABAY+'?'+urlencode(params)).get('hits', [])
    result, rejected = [], []
    for data in hits[:limit]:
        try: result.append(stock_record(project, provider, data))
        except ValueError as e: rejected.append({'id': str(data.get('id')), 'reason': str(e)})
    return result, rejected


def browser_task(provider, query, kind='video'):
    if provider == 'pexels' and kind != 'video': raise ValueError('Pexels provides no audio library')
    paths = {'pexels': ['/search/videos/'], 'pixabay': ['/videos/search/'] if kind=='video' else ['/music/search/', '/sound-effects/search/'],
             'mixkit': ['/free-stock-video/'] if kind=='video' else ['/free-stock-music/', '/free-sound-effects/']}
    host = {'pexels': 'www.pexels.com', 'pixabay': 'pixabay.com', 'mixkit': 'mixkit.co'}[provider]
    return {'provider': provider, 'query': query, 'kind': kind, 'mode': 'browser_assisted', 'candidates': [],
            'tasks': [{'entry_url': 'https://'+host+p, 'search_query': f'site:{host}' + ('/video/' if provider=='pexels' else p.replace('/search/', '/')) + ' ' + query} for p in paths[provider]],
            'next_action': 'Agent uses available web/browser tools to inspect individual item pages and selected download license; download normally, then import-web with receipt. No scraping or bulk download.',
            'notice': 'This is a browser search task, not completed search results.'}
