"""
rising.py — generate rising.json
Top 50 players by % ELO increase over last LOOKBACK cups, min rating MIN_RATING.
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

LOOKBACK   = 26
MIN_RATING = 1600

with open(_p('alldata.json')) as f:
    data = json.load(f)

current_cup = max(h['c'] for p in data['weighted'] for h in p['h'])
lookback_cup = current_cup - LOOKBACK

print(f"Current cup: {current_cup}  |  Comparing against cup {lookback_cup}")

output = {
    'current_cup':  current_cup,
    'lookback_cup': lookback_cup,
    'lookback_cups': LOOKBACK,
    'min_rating':   MIN_RATING,
}

for mode in ['standard', 'weighted']:
    players = data[mode]
    results = []
    for p in players:
        hist = sorted(p['h'], key=lambda h: h['c'])
        current_r = hist[-1]['r']
        if current_r < MIN_RATING:
            continue
        past = [h for h in hist if h['c'] <= lookback_cup]
        if not past:
            continue
        past_r = past[-1]['r']
        pct = round((current_r - past_r) / past_r * 100, 1)
        if pct < 1.0:
            continue
        results.append({
            'name':       p['n'],
            'rating_now': round(current_r, 1),
            'rating_then': round(past_r, 1),
            'pct':        pct,
        })

    results.sort(key=lambda x: x['pct'], reverse=True)
    output[mode] = results[:50]
    print(f"{mode}: {len(results)} qualifying players, top 50 saved")

with open(_p('rising.json'), 'w') as f:
    json.dump(output, f, indent=2)

print('\nrising.json written')
