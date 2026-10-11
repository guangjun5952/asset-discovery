"""Editable shot requests and evidence-aware retrieval. Sparse fallback is labelled."""
import json
import math
import re
from pathlib import Path
from .core import cosine, terms, now
from .intelligence import AI, semantic_text, rerank
from .rights import PROVIDERS, policy


def validate_plan(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get('needs'), list) or not plan['needs']:
        raise ValueError('Plan requires nonempty needs list')
    ids = set()
    for n in plan['needs']:
        if not isinstance(n.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', n['id']) or n['id'] in ids:
            raise ValueError('Need IDs must be unique safe names')
        ids.add(n['id'])
        if not isinstance(n.get('query'), str) or not n['query'].strip():
            raise ValueError('Each need requires query')
        if n.get('kind') not in ('video', 'audio') or n.get('route') not in ('local_only', 'online_only', 'local_first'):
            raise ValueError('Invalid need kind or route')
        for field in ('duration', 'at'):
            value = n.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (value <= 0 if field=='duration' else value < 0):
                raise ValueError(f'Invalid need {field}')
        for field in ('must', 'avoid'):
            if not isinstance(n.get(field, []), list) or any(not isinstance(x, str) for x in n.get(field, [])):
                raise ValueError(f'Need {field} must be a list of strings')
        if not isinstance(n.get('real_only', False), bool):
            raise ValueError('real_only must be boolean')
        if n['duration'] > 3600:
            raise ValueError('Need exceeds one-hour bound')
    return plan


def plan_script(project, script, use_ai=False):
    if use_ai:
        prompt = '''Analyze the script into editorial media needs. Prefer the user's screen recordings, personal footage and product proof from local_only; generic real-world B-roll uses local_first; explicit online-only uses online_only. Include sound design only if requested. Return {"method":"model","needs":[{"id":"shot-001","query":"precise Chinese shot and action with English synonyms","online_query":"short English stock search","kind":"video or audio","route":"local_only or local_first or online_only","duration":4.0,"at":0.0,"must":[],"avoid":[],"real_only":true}]}. at is target timeline seconds, duration is requested usable duration. Do not claim to know what local files exist. Do not replace user-specific proof with generic footage.'''
        return validate_plan(AI(project).chat(prompt, script))
    sentences = [s.strip() for s in re.split(r'[\n。！？]+', script) if s.strip()]
    needs, at = [], 0.0
    for i, text in enumerate(sentences):
        local = bool(re.search(r'录屏|我拍|我自己|我的|本地|实测|操作演示|screen\s*record|my footage', text, re.I))
        sound = bool(re.search(r'^\s*(音效|配乐|环境声|SFX|music)[:：]', text, re.I))
        dur = max(2, min(8, len(text)/5))
        needs.append({'id': f'shot-{i+1:03}', 'query': text, 'online_query': text, 'kind': 'audio' if sound else 'video',
                      'route': 'local_only' if local else 'local_first', 'duration': round(dur, 2), 'at': round(at, 2),
                      'must': [], 'avoid': [], 'real_only': True})
        if not sound:
            at += dur
    return validate_plan({'method': 'heuristic_draft_requires_editorial_review', 'created_at': now(), 'needs': needs})


def search(project, query, kind='video', duration=0, limit=5, source='any', use_embeddings=False, use_rerank=False, must=None, avoid=None, real_only=False):
    query_terms = terms(query)
    segments = project.segments()
    query_vector = AI(project).embedding(query) if use_embeddings else None
    identity = project.config['ai']['base_url'].rstrip('/')+'|'+project.config['ai'].get('embedding_model', '')
    results = []
    for s in segments:
        info = s['asset']
        online = info['provenance'].get('provider') in PROVIDERS
        if online:
            try: policy(project, info['provenance'])
            except ValueError: continue
        if info['kind'] != kind or s['end']-s['start']+1e-6 < duration or not Path(s['path']).exists():
            continue
        if (source == 'local' and online) or (source == 'online' and not online):
            continue
        text = semantic_text(s)
        st = terms(text)
        normalized = text.lower()
        if any(str(x).lower() not in normalized for x in (must or [])) or any(str(x).lower() in normalized for x in (avoid or [])):
            continue
        review = s.get('review') or {}
        reasons = []
        if review.get('reject') or (real_only and review.get('synthetic')):
            continue
        if kind == 'video' and min(info['width'], info['height']) < project.config['min_video_height']:
            continue
        if project.config['require_review'] and (not review or review.get('confidence', 0) < 0.5):
            reasons.append('needs_visual_or_audio_review')
        relevance = len(query_terms & st)/max(1, len(query_terms))
        method = 'text_overlap_not_semantic'
        if query_vector is not None and s.get('embedding_model') == identity:
            relevance = 0.3*relevance+0.7*max(0, cosine(query_vector, s['embedding']))
            method = 'hybrid_text_and_embedding'
        if relevance < project.config['min_relevance']:
            continue
        quality = s['quality']
        technical = 1.0
        if quality.get('dark_fraction', 0) > 0.95 or quality.get('bright_fraction', 0) > 0.95:
            technical -= 0.25
            reasons.append('mostly_dark_or_white_sample_check_intent')
        if quality.get('laplacian_variance', 999) < 15:
            technical -= 0.15
            reasons.append('low_detail_sample_check_focus_or_design')
        if s['audio'].get('max_volume', -10) >= -0.1:
            reasons.append('peak_near_full_scale_check_clipping')
        if kind=='audio' and s['audio'].get('max_volume', 0) < -50:
            technical -= 0.5
            reasons.append('very_quiet_audio')
        aesthetic = review.get('aesthetic', 0.5)
        usability = review.get('usability', 0.5)
        score = 0.65*relevance+0.15*aesthetic+0.1*usability+0.1*technical
        if review.get('has_people') or review.get('has_logos'):
            reasons.append('check_personality_trademark_or_property_permissions')
        s.update(score=round(score, 4), relevance=round(relevance, 4), retrieval_method=method,
                 warnings=reasons, eligible=not (project.config['require_review'] and (not review or review.get('confidence', 0)<0.5)),
                 rank_reason=f'relevance={relevance:.3f}; aesthetic={aesthetic:.2f}; usability={usability:.2f}; technical={technical:.2f}')
        results.append(s)
    results.sort(key=lambda s: s['score'], reverse=True)
    results = results[:max(1, min(limit, 50))]
    if use_rerank and results:
        results = rerank(project, query, results)
    return results


def assemble(project, plan, use_embeddings=False, use_rerank=False):
    validate_plan(plan)
    selected, missing, used = [], [], set()
    for need in plan['needs']:
        sources = ['local', 'online'] if need['route']=='local_first' else ['local' if need['route']=='local_only' else 'online']
        choices = []
        for source in sources:
            options = search(project, need['query'], need['kind'], need['duration'], 10, source,
                             use_embeddings, use_rerank, need.get('must'), need.get('avoid'), need.get('real_only', False))
            choices = [s for s in options if s['eligible'] and s['id'] not in used]
            if choices:
                break
        if not choices:
            missing.append({'need': need, 'reason': 'No unused reviewed segment meets duration, quality and relevance constraints',
                            'next_action': 'review_local_or_record' if need['route']=='local_only' else 'search_cc0_or_review_candidates'})
            continue
        s = choices[0]
        used.add(s['id'])
        selected.append({'need': need, 'segment_id': s['id'], 'source_path': s['path'], 'sha256': s['sha256'],
                         'source_in': s['start'], 'source_out': s['start']+need['duration'], 'timeline_at': need['at'],
                         'score': s['score'], 'reason': s['rank_reason'], 'review': s.get('review'),
                         'warnings': s['warnings'], 'provenance': s['asset']['provenance'], 'kind': need['kind']})
    return {'version': 1, 'created_at': now(), 'fps': project.config['fps'], 'width': project.config['width'],
            'height': project.config['height'], 'selections': selected, 'unresolved': missing,
            'status': 'ready' if not missing else 'incomplete'}


def choose(project, plan, decisions):
    """Validate query-specific Agent decisions after viewing candidate media.

    Unlike lexical assembly, an Agent may match synonyms and choose an interior subclip.
    Decisions are explicit evidence records, never inferred from a high filename score.
    """
    validate_plan(plan)
    needs = {n['id']: n for n in plan['needs']}
    segments = {s['id']: s for s in project.segments()}
    selections, seen = [], set()
    for decision in decisions:
        nid = decision['need_id']
        if nid not in needs or nid in seen:
            raise ValueError('Unknown or duplicate decision need_id')
        n = needs[nid]
        s = segments[decision['segment_id']]
        review = s.get('review') or {}
        if not review or review.get('reject') or review.get('confidence', 0) < 0.5:
            raise ValueError('Agent choice requires an accepted, sufficiently confident media review')
        if n.get('real_only') and review.get('synthetic'):
            raise ValueError('Synthetic segment cannot fulfill real_only need')
        online = s['asset']['provenance'].get('provider') in PROVIDERS
        if online: policy(project, s['asset']['provenance'])
        if (n['route']=='local_only' and online) or (n['route']=='online_only' and not online):
            raise ValueError('Decision violates source routing')
        if s['asset']['kind'] != n['kind']:
            raise ValueError('Decision media kind mismatch')
        if n['kind']=='video' and min(s['asset']['width'], s['asset']['height']) < project.config['min_video_height']:
            raise ValueError('Decision fails configured resolution floor')
        a = decision.get('source_in', s['start'])
        if not isinstance(a, (int, float)) or not math.isfinite(a) or a < s['start'] or a+n['duration'] > s['end']+1e-6:
            raise ValueError('Decision exceeds indexed segment time range')
        score = decision.get('score')
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1 or not str(decision.get('reason', '')).strip():
            raise ValueError('Decision needs a 0..1 score and visible/audible evidence reason')
        # Hard terms remain literal constraints; semantic interpretation belongs in query.
        text = semantic_text(s).lower()
        if any(str(x).lower() not in text for x in n.get('must', [])) or any(str(x).lower() in text for x in n.get('avoid', [])):
            raise ValueError('Decision violates must/avoid constraints')
        seen.add(nid)
        selections.append({'need': n, 'segment_id': s['id'], 'source_path': s['path'], 'sha256': s['sha256'],
                           'source_in': a, 'source_out': a+n['duration'], 'timeline_at': n['at'],
                           'score': score, 'reason': decision['reason'], 'review': review,
                           'warnings': ['Agent sampled-media judgement; check continuous action before final publish'],
                           'provenance': s['asset']['provenance'], 'kind': n['kind']})
    unresolved = [{'need': n, 'reason': 'No Agent decision supplied'} for n in plan['needs'] if n['id'] not in seen]
    return {'version': 1, 'created_at': now(), 'method': 'agent_multimodal_selection',
            'fps': project.config['fps'], 'width': project.config['width'], 'height': project.config['height'],
            'selections': selections, 'unresolved': unresolved, 'status': 'ready' if not unresolved else 'incomplete'}
