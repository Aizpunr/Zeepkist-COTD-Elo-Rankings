import re

log_path = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LogOutput.log"
with open(log_path) as f:
    lines = [l for l in f.readlines() if 'COTDTracker' in l]

mapper = '[20x]K410K3N'

# Parse rounds: each 'Doing eliminations' block is a round
rounds = []
current_round = []

for line in lines:
    if 'Doing eliminations with leaderboard' in line:
        if current_round:
            rounds.append(current_round)
        current_round = []
    elif 'Eliminating ' in line or 'Player ' in line:
        current_round.append(line)

if current_round:
    rounds.append(current_round)

# For each round, find who was eliminated and their time
elim_order = []  # (name, time, round_num)

for round_num, rnd in enumerate(rounds, 1):
    player_times = {}
    eliminated_names = []

    for line in rnd:
        m = re.search(r'Player (.+?): Time: (.+)', line)
        if m:
            player_times[m.group(1).strip()] = m.group(2).strip()

        m2 = re.search(r'Eliminating (?:DNF|on time): (.+)', line)
        if m2:
            name = m2.group(1).strip()
            if name not in eliminated_names:
                eliminated_names.append(name)

    for name in eliminated_names:
        if name != mapper:
            time = player_times.get(name, 'DNF')
            elim_order.append((name, time, round_num))

# Find winner (not eliminated, not mapper)
all_named = set()
for rnd in rounds:
    for line in rnd:
        m = re.search(r'Player (.+?): Time:', line)
        if m:
            all_named.add(m.group(1).strip())

elim_set = {e[0] for e in elim_order}
winner = [n for n in all_named if n not in elim_set and n != mapper][0]

# Get winner's last time
winner_time = None
for line in reversed(lines):
    m = re.search(r'Player ' + re.escape(winner) + r': Time: (.+)', line)
    if m:
        winner_time = m.group(1).strip()
        break

# Build leaderboard (reverse elim = best first)
elim_order.reverse()
leaderboard = [(winner, winner_time, None)] + [(n, t, r) for n, t, r in elim_order]

print(f"Cup 134 - Map: Urbs Noctu by [20x]K410K3N")
print(f"Players: {len(leaderboard)} (mapper excluded)")
print()
for i, (name, time, rnd) in enumerate(leaderboard):
    rnd_str = f"Round {rnd}" if rnd else "Winner"
    # Convert time from comma to period for display
    time_str = time.replace(',', '.') if time != 'DNF' else 'DNF'
    print(f"{i+1:2}. {name:40s} {time_str:>12s}   {rnd_str}")
