import argparse
import json
import shutil
import sys
from pathlib import Path
from .core import Project, read_json, write_json
from .media import index, import_reviews
from .intelligence import describe, embed, transcribe
from .planning import plan_script, search, assemble, choose
from .providers import search_online, download
from .web_import import import_web
from .exporting import review_packet, export


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local-first video asset discovery. See SKILL.md and README.md.')
    parser.add_argument('--project', default='./asset-project', help='Project state folder')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('doctor')
    p = sub.add_parser('plan'); p.add_argument('script'); p.add_argument('--ai', action='store_true'); p.add_argument('--out')
    p = sub.add_parser('index'); p.add_argument('roots', nargs='*')
    p = sub.add_parser('review'); p.add_argument('--out'); p.add_argument('--limit', type=int, default=20)
    p = sub.add_parser('import-review'); p.add_argument('file')
    for name in ('describe', 'embed', 'transcribe'):
        p = sub.add_parser(name); p.add_argument('--limit', type=int, default=10)
    p = sub.add_parser('search'); p.add_argument('query'); p.add_argument('--kind', choices=['video', 'audio'], default='video')
    p.add_argument('--duration', type=float, default=0); p.add_argument('--limit', type=int, default=5)
    p.add_argument('--source', choices=['any', 'local', 'online'], default='any')
    p.add_argument('--embeddings', action='store_true'); p.add_argument('--rerank', action='store_true'); p.add_argument('--out')
    p = sub.add_parser('assemble'); p.add_argument('plan'); p.add_argument('--embeddings', action='store_true')
    p.add_argument('--rerank', action='store_true'); p.add_argument('--out')
    p = sub.add_parser('choose'); p.add_argument('plan'); p.add_argument('decisions'); p.add_argument('--out')
    p = sub.add_parser('online-search'); p.add_argument('provider', choices=['commons', 'freesound', 'pexels', 'pixabay', 'mixkit']); p.add_argument('query')
    p.add_argument('--kind', choices=['video', 'audio'], default='video'); p.add_argument('--limit', type=int, default=5); p.add_argument('--out')
    p.add_argument('--browser', action='store_true')
    p = sub.add_parser('import-web'); p.add_argument('file'); p.add_argument('receipt')
    p = sub.add_parser('download'); p.add_argument('provider', choices=['commons', 'freesound', 'pexels', 'pixabay', 'mixkit']); p.add_argument('id'); p.add_argument('--original', action='store_true')
    p = sub.add_parser('export'); p.add_argument('selection'); p.add_argument('--out', required=True); p.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command=='doctor':
            result = {'python': sys.version.split()[0], 'ffmpeg': shutil.which('ffmpeg'), 'ffprobe': shutil.which('ffprobe'),
                      'project_exists': (Path(args.project)/'config.json').exists(), 'network_calls': 0}
            try:
                import xml.etree.ElementTree as ET
                ET.fromstring('<ok/>')
                result['xml_parser'] = 'ok'
            except ImportError:
                result['xml_parser'] = 'broken_python_expat_use_another_python_for_tests'
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ffmpeg'] and result['ffprobe'] else 1
        if args.command=='init':
            project = Project.init(args.project)
            result = {'project': str(project.path), 'config': str(project.path/'config.json')}
        else:
            project = Project(args.project)
            if args.command=='plan':
                result = plan_script(project, Path(args.script).read_text(encoding='utf-8'), args.ai)
                write_json(args.out or project.path/'plan.json', result)
            elif args.command=='index':
                result = index(project, args.roots)
            elif args.command=='review':
                result = review_packet(project, args.out or project.path/'review', args.limit)
            elif args.command=='import-review':
                result = import_reviews(project, args.file)
            elif args.command=='describe':
                result = describe(project, args.limit)
            elif args.command=='embed':
                result = embed(project, args.limit)
            elif args.command=='transcribe':
                result = transcribe(project, args.limit)
            elif args.command=='search':
                result = search(project, args.query, args.kind, args.duration, args.limit, args.source, args.embeddings, args.rerank)
                if args.out: write_json(args.out, result)
            elif args.command=='assemble':
                result = assemble(project, read_json(args.plan), args.embeddings, args.rerank)
                write_json(args.out or project.path/'selection.json', result)
            elif args.command=='choose':
                result = choose(project, read_json(args.plan), read_json(args.decisions))
                write_json(args.out or project.path/'selection.json', result)
            elif args.command=='online-search':
                result = search_online(project, args.provider, args.query, args.kind, args.limit, args.browser)
                if args.out: write_json(args.out, result)
            elif args.command=='import-web':
                result = import_web(project, args.file, args.receipt)
            elif args.command=='download':
                result = download(project, args.provider, args.id, args.original)
            elif args.command=='export':
                result = export(project, read_json(args.selection), args.out, args.allow_partial)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        project.db.close()
        return 2 if isinstance(result, dict) and result.get('errors') else 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as e:
        print(json.dumps({'error': str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
