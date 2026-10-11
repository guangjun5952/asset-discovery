"""License-aware editing policy. Copyright licenses and API eligibility stay separate."""
import re
from urllib.parse import urlsplit

CC0 = 'https://creativecommons.org/publicdomain/zero/1.0/'
PLATFORM_LICENSES = {
    'pexels': ('Pexels License', 'https://www.pexels.com/license/'),
    'pixabay': ('Pixabay Content License', 'https://pixabay.com/service/license-summary/'),
    'mixkit-video-free': ('Mixkit Stock Video Free License', 'https://mixkit.co/license/modal/videoFree/'),
    'mixkit-video-restricted': ('Mixkit Stock Video Restricted License', 'https://mixkit.co/license/modal/videoRestricted/'),
    'mixkit-music-free': ('Mixkit Stock Music Free License', 'https://mixkit.co/license/modal/musicFree/'),
    'mixkit-sfx-free': ('Mixkit Sound Effects Free License', 'https://mixkit.co/license/modal/sfxFree/')
}
PROVIDERS = ('commons', 'freesound', 'pexels', 'pixabay', 'mixkit')


def cc_license(url):
    if not isinstance(url, str): return None
    p = urlsplit(url.strip())
    if p.scheme not in ('http', 'https') or p.netloc.lower() != 'creativecommons.org' or p.query or p.fragment:
        return None
    if p.path.rstrip('/') == '/publicdomain/zero/1.0': return 'cc0'
    match = re.fullmatch(r'/licenses/(by|by-sa|by-nc|by-nc-sa|by-nd|by-nc-nd)/(1\.0|2\.0|2\.5|3\.0|4\.0)/?', p.path)
    return ('cc-'+match[1]+'-'+match[2]) if match else None


def policy(project, record):
    license_id = record.get('license_id') or cc_license(record.get('license_url'))
    if license_id in PLATFORM_LICENSES:
        if record.get('license_url') != PLATFORM_LICENSES[license_id][1]:
            raise ValueError('License ID and URL disagree')
    elif license_id and license_id != cc_license(record.get('license_url')):
        raise ValueError('License ID and URL disagree')
    settings = project.config.get('online', {})
    mode = settings.get('license_mode', 'commercial_edit')
    if mode not in ('commercial_edit', 'strict_cc0'):
        raise ValueError('license_mode must be commercial_edit or strict_cc0')
    if mode == 'strict_cc0' and license_id != 'cc0':
        raise ValueError('Project uses strict_cc0; other licenses excluded')
    attribution = bool(license_id and re.fullmatch(r'cc-by-(1\.0|2\.0|2\.5|3\.0|4\.0)', license_id))
    if not (license_id == 'cc0' or attribution or license_id in PLATFORM_LICENSES):
        raise ValueError('Unknown, NC, ND or ShareAlike license requires separate review; not auto-selected')
    if license_id == 'mixkit-video-restricted':
        raise ValueError('Mixkit Restricted excluded from commercial-edit workflow')
    if license_id == 'mixkit-music-free' and settings.get('intended_use', 'web_video') not in ('web_video', 'podcast'):
        raise ValueError('Mixkit Music excluded for this distribution use (TV/radio/games/discs)')
    if attribution and not (record.get('author') and record.get('source_page')):
        raise ValueError('CC BY requires author and source to generate attribution')
    return {'license_id': license_id, 'attribution_required': attribution,
            'standalone_redistribution': license_id == 'cc0' or attribution,
            'intended_use': settings.get('intended_use', 'web_video'),
            'decision': 'accepted_for_editing_subject_to_terms',
            'notice': 'Copyright license only; people, marks and other third-party rights require shot-specific review.'}


def apply_policy(project, record):
    decision = policy(project, record)
    return dict(record, **decision)
