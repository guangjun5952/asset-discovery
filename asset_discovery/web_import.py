"""Register a file downloaded through normal website UI with explicit review evidence."""
import shutil
import re
from pathlib import Path
from urllib.parse import urlsplit
from .core import probe, sha, read_json, write_json, now
from .rights import PLATFORM_LICENSES, apply_policy


def import_web(project, filename, receipt_path):
    source = Path(filename).expanduser().resolve()
    receipt_path = Path(receipt_path).resolve()
    r = read_json(receipt_path)
    provider = r.get('provider')
    expected = {'pexels': 'pexels.com', 'pixabay': 'pixabay.com', 'mixkit': 'mixkit.co'}.get(provider)
    page = urlsplit(r.get('source_page', ''))
    if not expected or page.scheme!='https' or page.hostname not in (expected, 'www.'+expected) or page.username or page.password or not page.path.strip('/'):
        raise ValueError('Receipt must identify a specific supported provider item page')
    ident = r.get('license_id')
    permitted = {'pexels': {'pexels'}, 'pixabay': {'pixabay'}, 'mixkit': {k for k in PLATFORM_LICENSES if k.startswith('mixkit-')}}[provider]
    if ident not in permitted or r.get('license_url') != PLATFORM_LICENSES[ident][1]:
        raise ValueError('Receipt license does not match provider')
    if r.get('reviewed') is not True or not all(isinstance(r.get(k), str) and r[k].strip() for k in ('title', 'license_observed_text', 'variant', 'checked_at')):
        raise ValueError('Receipt requires actual page review, observed license text, variant, title and checked_at')
    digest = sha(source)
    if r.get('sha256') != digest: raise ValueError('Receipt must bind the exact downloaded file SHA-256')
    evidence = Path(r.get('evidence_file', ''))
    if not evidence.is_absolute(): evidence = receipt_path.parent/evidence
    if not evidence.is_file() or evidence.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.pdf', '.html', '.txt', '.json'):
        raise ValueError('Save page screenshot/text/download license as evidence_file')
    info = probe(source)
    if ident.startswith('mixkit-video') and info['kind']!='video': raise ValueError('Video license cannot label audio')
    if ident in ('mixkit-music-free', 'mixkit-sfx-free') and info['kind']!='audio': raise ValueError('Audio license cannot label video')
    record = apply_policy(project, dict(r, provider=provider, license_name=PLATFORM_LICENSES[ident][0],
                          kind=info['kind'], license_status='agent_or_user_page_review',
                          description=r.get('description', r['title']), registered_at=now()))
    folder = project.path/'downloads'; folder.mkdir(exist_ok=True)
    target = folder/(provider+'-'+digest[:20]+source.suffix.lower())
    if target.exists() and sha(target)!=digest: raise ValueError('Destination collision')
    if not target.exists(): shutil.copy2(source, target)
    proof = folder/(provider+'-'+digest[:20]+'.evidence'+evidence.suffix.lower())
    if evidence.resolve()!=proof.resolve(): shutil.copy2(evidence, proof)
    record.update(local_path=str(target), evidence_file=str(proof), evidence_sha256=sha(proof))
    write_json(str(target)+'.license.json', record)
    write_json(str(target)+'.asset.json', {'description': record['description'], 'tags': [r['title']]})
    return {'path': str(target), 'license_id': ident, 'license_status': record['license_status'], 'next_action': 'index then review the media'}
