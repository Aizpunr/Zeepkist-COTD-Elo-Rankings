"""
build_cup_links.py - the links shown next to each map on the cups table.

  zc       the map's page on ZeepCentraal (zeepki.st/level/<id>)
  lexer    Lexer's YouTube video of the cup
  sandals  Sandals' YouTube video of the cup

cup_links.json is the source of truth and index.html reads it directly, so a
new link never touches the rating pipeline. It is hand-editable: this script
only fills keys that are missing and never changes one that is already there.
An empty string means "checked, there is none" and blocks a wrong auto-match.

Where the links come from:
  zc      Cups with a livelog: the level id in its ROUND_STARTED lines is GTR's
          level hash, and GTR gives the id ZeepCentraal uses (xxHash) for it.
          Older cups: a GTR lookup by map name, accepted only when the level's
          author is the cup's mapper.
  videos  The two playlists carry no cup numbers, so a video is matched by the
          cup number its description states, or else by date: the latest cup on
          or up to MAX_GAP days before the video was published.

Anything the rules cannot settle is written to cup_links_review.txt (ignored by
git) to be resolved by hand in cup_links.json. Network trouble never fails the
pipeline: the script warns, keeps what it has and exits 0.

Usage: python build_cup_links.py [--levels-only | --videos-only]
"""
import datetime, difflib, json, os, re, shutil, subprocess, sys, time, urllib.request

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

LINKS   = _p('cup_links.json')
VIDEOS  = _p('cup_videos.json')      # cache: one entry per playlist video; add "skip": true by hand to one that is not a cup
REVIEW  = _p('cup_links_review.txt')
PLAYLISTS = {
    'lexer':   'PLIzebc4t5e1e8k4pPTzD0ZbvlAKbj7gRI',
    'sandals': 'PL9E3sT3ScWMQpWLWkFQHbbbhHdLOXeY9I',
}
# Sandals' playlist also holds Eggy Cup, Author Time Hunt and tournament videos,
# some published on a COTD day, so his date matches need the mapper's name too.
NEEDS_MAPPER = {'sandals'}
MAX_GAP = 3                          # days between a cup and its video
GTR = 'https://graphql.zeepki.st'
# 'Stroll' and '(non-troll)' are regular cups: both showed up in Lexer's titles.
SPECIAL = re.compile(r'(?<!non-)\btroll|\broulette|\bshuffl', re.I)


# ── small helpers ───────────────────────────────────────────
def norm(s):
    """Name without clan tags, case or punctuation: '[TTR] Tiger' -> 'tiger'."""
    return re.sub(r'[^a-z0-9]', '', re.sub(r'\[[^\]]*\]', '', s or '').lower())


def mapper_names(mapper):
    return [n for n in (norm(x) for x in re.split(r',|&|/|\+|\band\b', mapper or '')) if n]


def same_person(a, b):
    """Same name allowing for tags, a short form ('OLR' for 'OLR94') or a typo
    ('Redstoney' for 'Redstony')."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a)):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(path, obj):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write('\n')


def load_cups():
    """Cups in the order of cups.json (chronological), date as a date or None."""
    cups = []
    for c in load_json(_p('cups.json'), []):
        d = c.get('date')
        cups.append({'id': c['id'], 'map': c.get('map') or '', 'mapper': c.get('mapper') or '',
                     'date': datetime.date.fromisoformat(d) if d else None})
    return cups


# ── ZeepCentraal: level id per cup ──────────────────────────
_last = [0.0]

def gql(query):
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(GTR, data=json.dumps({'query': query}).encode(),
                                 headers={'Content-Type': 'application/json',
                                          'User-Agent': 'cotd-elo-rankings/1.0'})
    doc = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if doc.get('errors'):
        raise RuntimeError(f"GTR: {doc['errors']}")
    return doc['data']


def livelog_hash(cup):
    """GTR level hash of the map the cup was played on, read from its livelog."""
    m = re.fullmatch(r'COTD (\d+)', cup['id'])
    if not m or not cup['date']:
        return None
    path = _p(os.path.join('cup logs', f'cotd_{m.group(1)}_liveleaderboard.log'))
    if not os.path.exists(path):
        return None
    day, seen = cup['date'].isoformat(), {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            # The livelog is cumulative: only this cup's evening counts.
            if line.startswith(day) and 'ROUND_STARTED|' in line:
                parts = line.rstrip('\n').split('ROUND_STARTED|', 1)[1].split('|')
                if len(parts) >= 3:
                    seen[parts[1]] = seen.get(parts[1], 0) + 1
    if not seen:
        return None
    best = max(seen, key=seen.get)
    return best if seen[best] >= 5 else None


def level_by_hash(h):
    nodes = gql('{levels(filter:{hash:{equalTo:%s}}){nodes{xxHash}}}' % json.dumps(h))['levels']['nodes']
    return nodes[0]['xxHash'] if nodes else None


def levels_by_name(name, exact=True):
    """[{xx, name, author, records}] for GTR levels with this name (or, with
    exact=False, containing it), busiest first."""
    op = 'equalToInsensitive' if exact else 'includesInsensitive'
    q = ('{levelItems(filter:{name:{%s:%s},deleted:{equalTo:false}},first:100)'
         '{nodes{name fileAuthor level{xxHash records{totalCount}}}}}' % (op, json.dumps(name)))
    out = {}
    for n in gql(q)['levelItems']['nodes']:
        lv = n.get('level') or {}
        if lv.get('xxHash'):
            out[lv['xxHash']] = {'xx': lv['xxHash'], 'name': n['name'], 'author': n.get('fileAuthor') or '',
                                 'records': (lv.get('records') or {}).get('totalCount', 0)}
    return sorted(out.values(), key=lambda x: -x['records'])


def core_name(name):
    """The distinctive part of a map name: 'COTD #61 - Sandy Burrow' -> 'Sandy Burrow'.
    Cut at apostrophes too, because the sheet and the workshop type them differently."""
    s = re.sub(r'\(?\bCOTD\b\)?\s*#?\s*\d*', ' ', name, flags=re.I)
    pieces = [p.strip(' -:_') for p in re.split(r"['’`\"]", s)]
    return max(pieces, key=len) if pieces else ''


def find_level(cup):
    """(xxHash or None, note for the review file or None)."""
    h = livelog_hash(cup)
    if h:
        xx = level_by_hash(h)
        if xx:
            return xx, None
    if not cup['map']:
        return None, 'no map name'
    mappers = mapper_names(cup['mapper'])
    by_mapper = lambda found: [c for c in found if any(same_person(c['author'], m) for m in mappers)]

    found = levels_by_name(cup['map'])
    mine = by_mapper(found)
    if mine:
        # Several versions of one map: the cup lobby makes its version the busiest.
        return mine[0]['xx'], None
    # The sheet's name is often not the workshop's ('Sandy Burrow' for 'COTW #61
    # - Sandy Burrow'): search by the distinctive part, and only trust the mapper's own level.
    core = core_name(cup['map'])
    if len(core) >= 4 and mappers:
        mine = by_mapper(levels_by_name(core, exact=False))
        if mine:
            return mine[0]['xx'], (f"matched loosely to {mine[0]['name']!r} by {mine[0]['author']} "
                                   f"({mine[0]['records']} records): worth a look")
    if found:
        cands = '; '.join(f"{c['xx']} by {c['author']} ({c['records']} records)" for c in found[:4])
        return None, f"author is not the mapper: {cands}"
    return None, f'no GTR level by the mapper with {core!r} in its name'


# ── YouTube: playlist listing and video dates ───────────────
YT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cookie': 'SOCS=CAI; CONSENT=YES+1',     # skips the EU consent interstitial
}

def yt(url, body=None):
    h = dict(YT_HEADERS)
    if body is not None:
        h['Content-Type'] = 'application/json'
        body = json.dumps(body).encode()
    req = urllib.request.Request(url, data=body, headers=h)
    return urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')


def walk(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, key)


def playlist(pid):
    """[(video id, title)] for the whole playlist, in playlist order."""
    html = yt('https://www.youtube.com/playlist?list=' + pid)
    data = json.loads(re.search(r'var ytInitialData = (\{.*?\});</script>', html, re.S).group(1))
    version = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html).group(1)
    out, used = {}, set()
    for _ in range(50):                       # 100 videos per page
        for r in walk(data, 'lockupViewModel'):
            if r.get('contentType', 'LOCKUP_CONTENT_TYPE_VIDEO') == 'LOCKUP_CONTENT_TYPE_VIDEO':
                meta = r.get('metadata', {}).get('lockupMetadataViewModel', {})
                out.setdefault(r['contentId'], meta.get('title', {}).get('content', ''))
        for r in walk(data, 'playlistVideoRenderer'):      # the page's older format
            out.setdefault(r['videoId'], ''.join(x.get('text', '') for x in r.get('title', {}).get('runs', [])))
        tokens = [c['token'] for key in ('continuationItemViewModel', 'continuationItemRenderer')
                  for item in walk(data, key) for c in walk(item, 'continuationCommand') if 'token' in c]
        tokens = [t for t in tokens if t not in used]
        if not tokens:
            break
        used.add(tokens[0])
        data = json.loads(yt('https://www.youtube.com/youtubei/v1/browse?prettyPrint=false',
                             {'context': {'client': {'clientName': 'WEB', 'clientVersion': version, 'hl': 'en'}},
                              'continuation': tokens[0]}))
    return list(out.items())


def video_meta(vid):
    """(publish date 'YYYY-MM-DD', first lines of the description)."""
    url = 'https://www.youtube.com/watch?v=' + vid
    try:
        html = yt(url)
        m = re.search(r'"publishDate":"(\d{4}-\d{2}-\d{2})', html)
        if not m:
            raise RuntimeError(f'no publish date on the page of {vid}')
        d = re.search(r'"shortDescription":("(?:[^"\\]|\\.)*")', html)
        return m.group(1), (json.loads(d.group(1)) if d else '')[:400]
    except Exception:
        # YouTube answers 429 to plain page reads after a burst of them.
        # yt-dlp, when installed, still gets through (slower, about 8 s).
        tool = shutil.which('yt-dlp')
        if not tool:
            raise
        r = subprocess.run([tool, '--no-update', '--skip-download', '--print',
                            '%(.{upload_date,description})j', url],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
        lines = (r.stdout or '').strip().splitlines()
        if not lines:
            raise RuntimeError('YouTube refused both the page read and yt-dlp')
        d = json.loads(lines[-1])
        u = d['upload_date']
        return f'{u[:4]}-{u[4:6]}-{u[6:]}', (d.get('description') or '')[:400]


def refresh_videos(cache):
    """Add every playlist video missing from the cache. Returns how many were added."""
    added = 0
    for channel, pid in PLAYLISTS.items():
        for vid, title in playlist(pid):
            if vid in cache:
                continue
            try:
                date, desc = video_meta(vid)
            except Exception as e:
                print(f"  WARNING: no date for {channel}'s video {vid} ({title!r}): {e}")
                continue
            cache[vid] = {'ch': channel, 'title': title, 'date': date, 'desc': desc}
            added += 1
            time.sleep(0.3)
    return added


# ── matching videos to cups (pure: tested in tests/test_cup_links.py) ──
def stated_cup(video):
    """The cup a title or description names ('this is COTD 26', 'COTD #32'), or
    None when it names none or more than one."""
    text = f"{video.get('title') or ''}\n{video.get('desc') or ''}"
    found = {f"{'Troll ' if m.group(1) else ''}COTD {int(m.group(2))}"
             for m in re.finditer(r'\b(troll\s+)?COTD\s*#?\s*(\d{1,3})\b', text, re.I)}
    return found.pop() if len(found) == 1 else None


MAPPER_PATTERNS = (
    r'\bmap (?:made )?by ([^\n!.,(]+)',                               # Lexer: "Map by L3it3R"
    r'\bthanks to ([^\n!.,(]+?) for (?:making|building|creating)',    # Sandals: "Thanks to OLR for making this week's map"
)

def stated_mapper(video):
    for pat in MAPPER_PATTERNS:
        m = re.search(pat, video.get('desc') or '', re.I)
        if m:
            return m.group(1).strip()
    return None


def match_videos(cups, videos, need_mapper=False):
    """Match one channel's videos to cups.

    cups:   [{'id', 'date' (date or None), 'mapper'}] in chronological order
    videos: [{'id', 'title', 'date' ('YYYY-MM-DD'), 'desc'}]
    need_mapper: a date match only counts when the description names the cup's
            mapper (for a playlist that also holds videos of other events).
    Returns ({cup id: video id}, [(video id, reason)]) where the second list is
    what a person has to look at.
    """
    by_id = {c['id']: c for c in cups}
    dated = sorted((c for c in cups if c['date']), key=lambda c: c['date'])
    claims, review = {}, []                    # cup id -> [video], leftovers

    for v in videos:
        day = datetime.date.fromisoformat(v['date'])
        before = [c for c in dated if c['date'] <= day]
        by_date = before[-1] if before and (day - before[-1]['date']).days <= MAX_GAP else None
        special = bool(SPECIAL.search(v.get('title') or '') or SPECIAL.search(v.get('desc') or ''))

        named = stated_cup(v)
        if named:
            if named not in by_id:
                review.append((v['id'], f'it names {named}, which is not a cup we have'))
            elif by_date and by_date['id'] != named and by_id[named]['date'] and not special:
                # One of the two is wrong (a stray number, or a wrong cup date).
                review.append((v['id'], f"it names {named} but its date points at {by_date['id']}"))
            else:
                claims.setdefault(named, []).append(v)
            continue
        if special:
            review.append((v['id'], 'Troll or Roulette cup: those have no date to match on'))
            continue
        if not by_date:
            near = f"{before[-1]['id']} was {(day - before[-1]['date']).days} days earlier" if before else 'before the first cup'
            review.append((v['id'], f'no cup within {MAX_GAP} days before it ({near})'))
            continue
        cup = by_date
        said = stated_mapper(v)
        if need_mapper and not said:
            review.append((v['id'], f"date points at {cup['id']}, but the description names no mapper to confirm it is a cup"))
            continue
        if said and cup['mapper'] and not any(same_person(said, m) for m in mapper_names(cup['mapper'])):
            review.append((v['id'], f"date points at {cup['id']} by {cup['mapper']}, description says map by {said}"))
            continue
        claims.setdefault(cup['id'], []).append(v)

    matched = {}
    for cid, vs in claims.items():
        if len(vs) == 1:
            matched[cid] = vs[0]['id']
        else:
            for v in vs:
                review.append((v['id'], f'{len(vs)} videos point at {cid}'))
    return matched, review


# ── main ────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    do_levels = '--videos-only' not in sys.argv
    do_videos = '--levels-only' not in sys.argv
    cups = load_cups()
    links = load_json(LINKS, {})
    videos = load_json(VIDEOS, {})
    notes = []

    if do_levels:
        todo = [c for c in cups if 'zc' not in links.get(c['id'], {})]
        found = 0
        try:
            for c in todo:
                xx, note = find_level(c)
                if xx:
                    links.setdefault(c['id'], {})['zc'] = xx
                    found += 1
                if note:
                    notes.append(f"MAP    {c['id']:16} {c['map']!r} by {c['mapper']!r}: {note}")
        except Exception as e:
            print(f"  WARNING: GTR lookup stopped ({e}). Kept what was found; run again later.")
        print(f"  ZeepCentraal: {found} new, {sum(1 for c in cups if links.get(c['id'], {}).get('zc'))} of {len(cups)} cups linked")

    if do_videos:
        try:
            added = refresh_videos(videos)
            print(f"  YouTube: {added} new videos, {len(videos)} known")
        except Exception as e:
            print(f"  WARNING: YouTube listing stopped ({e}). Matching what is already cached.")
        save_json(VIDEOS, videos)
        used = {l[ch] for l in links.values() for ch in PLAYLISTS if l.get(ch)}
        for channel in PLAYLISTS:
            # "skip": true in cup_videos.json marks a playlist video that is not a cup.
            mine = [dict(v, id=vid) for vid, v in videos.items() if v['ch'] == channel and not v.get('skip')]
            matched, review = match_videos(cups, mine, need_mapper=channel in NEEDS_MAPPER)
            new = 0
            for cid, vid in matched.items():
                if channel not in links.get(cid, {}) and vid not in used:
                    links.setdefault(cid, {})[channel] = vid
                    new += 1
            used = {l[ch] for l in links.values() for ch in PLAYLISTS if l.get(ch)}
            for vid, reason in review:
                if vid not in used:
                    v = videos[vid]
                    notes.append(f"VIDEO  {channel:8} {vid} {v['date']} {v['title']!r}: {reason}")
            for vid in (m for m in matched.values() if m not in used):
                v = videos[vid]
                notes.append(f"VIDEO  {channel:8} {vid} {v['date']} {v['title']!r}: its cup already has another video")
            have = sum(1 for c in cups if links.get(c['id'], {}).get(channel))
            print(f"  {channel}: {new} new, {have} of {len(cups)} cups linked")

    order = {c['id']: i for i, c in enumerate(cups)}
    links = dict(sorted(links.items(), key=lambda kv: order.get(kv[0], 10**6)))
    save_json(LINKS, links)
    with open(REVIEW, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(notes) + ('\n' if notes else ''))
    print(f"  cup_links.json written. {len(notes)} items to look at"
          + (f" in {os.path.basename(REVIEW)}" if notes else ''))


if __name__ == '__main__':
    main()
