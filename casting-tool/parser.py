"""
parser.py — Shared log parsing logic for real-time and batch processing.
Extracts COTDTracker events from BepInEx logs.
"""
import re
import json
import os

LOG_PATH_REAL = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LogOutput.log"
LOG_PATH_TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_log.txt')
LOG_PATH = LOG_PATH_REAL  # Overridden by server.py --test flag
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


class CupState:
    """Tracks live cup state as rounds happen."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.current_round = 0
        self.alive_players = []       # names still in
        self.eliminated = []          # [(name, time, round), ...] in elimination order
        self.round_times = {}         # {name: time_str} for current round
        self.player_round_times = {}  # {name: [(round, time_str), ...]} across all rounds
        self.round_eliminations = []  # names eliminated this round (building up)
        self.all_players = []         # everyone who appeared
        self.winner = None
        self.cup_over = False
        self._in_elimination = False  # currently processing eliminations
        self._pending_round = False   # leaderboard seen, waiting for eliminations
        self._enrichment = {}         # {name: {elo, race_elo, race_rank, wins, ...}}

    def load_enrichment(self):
        """Load alldata.json for player stats enrichment."""
        path = os.path.join(DATA_DIR, 'alldata.json')
        if not os.path.exists(path):
            return
        with open(path, encoding='utf-8') as f:
            data = json.load(f)

        # Build lookup from weighted (all-time) data
        weighted = data.get('weighted', [])
        season = data.get('season_2026', [])

        # Index by name
        w_map = {p['n']: p for p in weighted}
        s_map = {p['n']: p for p in season}

        # Build race rank lookup
        season_sorted = sorted(season, key=lambda p: p['r'], reverse=True)
        race_ranks = {p['n']: i + 1 for i, p in enumerate(season_sorted)}

        self._w_map = w_map
        self._s_map = s_map
        self._race_ranks = race_ranks

        # Build reverse alias map from elo_engine.py CANONICAL
        self._alias = {}
        elo_path = os.path.join(DATA_DIR, 'elo_engine.py')
        if os.path.exists(elo_path):
            with open(elo_path, encoding='utf-8') as f:
                src = f.read()
            m = re.search(r'CANONICAL\s*=\s*\{(.+?)\n\}', src, re.DOTALL)
            if m:
                try:
                    canonical = eval('{' + m.group(1) + '\n}')
                    for canon, aliases in canonical.items():
                        for alias in aliases:
                            self._alias[alias] = canon
                            # Also map tag-stripped version
                            stripped = re.sub(r'^\[.*?\]\s*', '', alias)
                            if stripped != alias:
                                self._alias[stripped] = canon
                except:
                    pass

    def enrich_player(self, name):
        """Get enrichment data for a player name."""
        alias = getattr(self, '_alias', {})
        def find(lookup, n):
            if n in lookup:
                return lookup[n]
            stripped = re.sub(r'^\[.*?\]\s*', '', n)
            if stripped in lookup:
                return lookup[stripped]
            # Try canonical alias
            canon = alias.get(n) or alias.get(stripped)
            if canon and canon in lookup:
                return lookup[canon]
            return None

        w = find(getattr(self, '_w_map', {}), name)
        s = find(getattr(self, '_s_map', {}), name)
        stripped = re.sub(r'^\[.*?\]\s*', '', name)
        canon = alias.get(name) or alias.get(stripped)
        rr = getattr(self, '_race_ranks', {}).get(canon or stripped)
        if rr is None:
            rr = getattr(self, '_race_ranks', {}).get(name)

        info = {'name': name}
        if w:
            info['elo'] = round(w['r'], 1)
            info['wins'] = w.get('w', 0)
            info['podiums'] = w.get('g', 0) + w.get('s', 0) + w.get('z', 0)
            info['cups'] = w.get('c', 0)
            info['best'] = w.get('b', 0)
            info['peak'] = round(w.get('p', 0), 1)
        if s:
            info['race_elo'] = round(s['r'], 1)
            info['race_wins'] = s.get('w', 0)
            info['race_podiums'] = s.get('g', 0) + s.get('s', 0) + s.get('z', 0)
            info['race_cups'] = s.get('c', 0)
        if rr:
            info['race_rank'] = rr
        return info

    def process_line(self, line):
        """Process a single COTDTracker log line. Returns event dict, list of events, or None."""
        if 'COTDTracker' not in line:
            return None

        # Round start (leaderboard seen — don't increment yet, discovery rounds have no elims)
        if 'Doing eliminations with leaderboard' in line:
            self._pending_round = True
            self.round_times = {}
            self.round_eliminations = []
            self._in_elimination = True
            return None

        # Player time
        m = re.search(r'Player (.+?): Time: (.+)', line)
        if m:
            name = m.group(1).strip()
            time_str = m.group(2).strip()
            self.round_times[name] = time_str
            if name not in self.all_players:
                self.all_players.append(name)
                self.alive_players.append(name)
            return None  # Don't broadcast individual times, wait for round end

        # Elimination
        m2 = re.search(r'Eliminating (DNF|on time): (.+)', line)
        if m2:
            # First elimination confirms this is a real round (not discovery)
            events = []
            if self._pending_round:
                self.current_round += 1
                self._pending_round = False
                events.append({
                    'type': 'round_start',
                    'round': self.current_round,
                    'alive_count': len(self.alive_players),
                })
            elim_type = m2.group(1)
            name = m2.group(2).strip()
            time_val = self.round_times.get(name, 'DNF')
            self.eliminated.append((name, time_val, self.current_round))
            if name in self.alive_players:
                self.alive_players.remove(name)
            self.round_eliminations.append(name)
            events.append({
                'type': 'player_eliminated',
                'name': name,
                'time': time_val,
                'round': self.current_round,
                'elim_type': elim_type,
                'info': self.enrich_player(name),
                'alive_count': len(self.alive_players),
            })
            return events if len(events) > 1 else events[0]

        # "Eliminating N players:" is the final summary line (end of round)
        # Ignore "Eliminated N DNF players" — that's just the DNF subtotal
        m3 = re.search(r'Eliminating (\d+) players:', line)
        if m3:
            count = int(m3.group(1))
            self._in_elimination = False

            # Accumulate per-player round times
            for name, time_str in self.round_times.items():
                if name not in self.player_round_times:
                    self.player_round_times[name] = []
                self.player_round_times[name].append((self.current_round, time_str))

            # Build round summary with times
            round_data = []
            for name, time_str in self.round_times.items():
                entry = {'name': name, 'time': time_str, 'info': self.enrich_player(name)}
                entry['eliminated'] = name in self.round_eliminations
                round_data.append(entry)

            # Sort by time (DNF last)
            def sort_key(e):
                t = e['time']
                if t == 'DNF':
                    return 999999
                return float(t.replace(',', '.'))
            round_data.sort(key=sort_key)

            return {
                'type': 'round_end',
                'round': self.current_round,
                'eliminated_count': count,
                'eliminated_names': list(self.round_eliminations),
                'round_data': round_data,
                'alive': [self.enrich_player(n) for n in self.alive_players],
                'alive_count': len(self.alive_players),
                'total_players': len(self.all_players),
                'player_round_times': {
                    name: [{'round': r, 'time': t} for r, t in times]
                    for name, times in self.player_round_times.items()
                },
            }

        # Cup winner
        m4 = re.search(r'Winner[:\s]+(.+)', line)
        if m4:
            self.winner = m4.group(1).strip()
            self.cup_over = True
            return {
                'type': 'cup_end',
                'winner': self.winner,
                'winner_info': self.enrich_player(self.winner),
                'total_rounds': self.current_round,
                'total_players': len(self.all_players),
            }

        return None

    def cup_strength(self):
        """Compute cup strength for current lobby using same formula as index.html."""
        w_map = getattr(self, '_w_map', {})
        if not w_map or not self.all_players:
            return None
        # Build normalized pool: rank 1 = 2000, proportional scaling, cap 196
        pool = sorted(w_map.values(), key=lambda p: p['r'], reverse=True)[:196]
        if not pool:
            return None
        max_r = pool[0]['r']
        scale = 2000 / max_r
        norm = {p['n']: p['r'] * scale for p in pool}
        # Get top 10 normalized ELOs of lobby participants
        alias = getattr(self, '_alias', {})
        def find_norm(name):
            if name in norm:
                return norm[name]
            stripped = re.sub(r'^\[.*?\]\s*', '', name)
            if stripped in norm:
                return norm[stripped]
            canon = alias.get(name) or alias.get(stripped)
            if canon:
                return norm.get(canon)
        elos = sorted([e for e in (find_norm(n) for n in self.all_players) if e is not None], reverse=True)[:10]
        if not elos:
            return None
        min_pool = min(norm.values())
        while len(elos) < 10:
            elos.append(min_pool)
        avg = sum(elos) / len(elos)
        return round(avg / 1850 * 100, 1)

    def get_state(self):
        """Get full current state for new overlay connections."""
        return {
            'type': 'full_state',
            'current_round': self.current_round,
            'alive': [self.enrich_player(n) for n in self.alive_players],
            'alive_count': len(self.alive_players),
            'eliminated': [
                {**self.enrich_player(n), 'time': t, 'round': r}
                for n, t, r in self.eliminated
            ],
            'total_players': len(self.all_players),
            'winner': self.winner,
            'cup_over': self.cup_over,
            'cup_strength': self.cup_strength(),
            'player_round_times': {
                name: [{'round': r, 'time': t} for r, t in times]
                for name, times in self.player_round_times.items()
            },
        }
