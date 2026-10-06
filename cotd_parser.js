/* cotd_parser.js: line-for-line JavaScript port of cotd_parser.py.
 *
 * Runs in the browser (window.CotdParser, used by submit.html to preview a
 * log before upload) and under Node (require, used by tests/js/). No build
 * step, no dependencies.
 *
 * The Python module is the source of truth. This port must produce the same
 * cup_<N>.json bytes for every golden fixture under tests/fixtures/ (checked
 * by tests/js/run_fixtures.mjs, which pytest runs via tests/test_parser_js.py).
 * Do not "improve" a rule here without changing cotd_parser.py first.
 *
 * Python semantics that JavaScript does not share, and how they are kept:
 *   round()        half-to-even            -> pyRound (never Math.round)
 *   sorted(str)    code-point order        -> cmpCodePoints (not default sort,
 *                                             which is UTF-16 code-unit order)
 *   str.strip()    Python whitespace class -> pyStrip (never trim)
 *   float()        raises on garbage       -> pyFloat (never parseFloat/Number)
 *   re '.'         any char except \n      -> [^\n] in every pattern
 *   readlines()    universal newlines      -> splitLines
 *   dict/set       any string key          -> Map/Set (no __proto__ traps)
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.CotdParser = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var TRACKER_TAG = 'COTDTracker';

  // Python '.' matches anything but '\n'; [^\n] is that exactly.
  var RE_PLAYER_TIME = /Player ([^\n]+?): Time: ([^\n]+)/;
  var RE_PLAYER_NAMED = /Player ([^\n]+?): Time:/;
  var RE_ELIMINATED = /Eliminating (?:DNF|on time): ([^\n]+)/;
  var RE_HAS_ELIM = /Eliminating (?:DNF|on time):/;

  function ParseError(message) {
    var e = new Error(message);
    Object.setPrototypeOf(e, ParseError.prototype);
    return e;
  }
  ParseError.prototype = Object.create(Error.prototype);
  ParseError.prototype.constructor = ParseError;
  ParseError.prototype.name = 'ParseError';

  function PyValueError(message) {
    var e = new Error(message);
    Object.setPrototypeOf(e, PyValueError.prototype);
    return e;
  }
  PyValueError.prototype = Object.create(Error.prototype);
  PyValueError.prototype.constructor = PyValueError;
  PyValueError.prototype.name = 'ValueError';

  // ── Python primitives ──────────────────────────────────────────────

  // Characters for which Python's str.isspace() is true.
  var PY_WS = '\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  var RE_LSTRIP = new RegExp('^[' + PY_WS + ']+');
  var RE_RSTRIP = new RegExp('[' + PY_WS + ']+$');

  function pyStrip(s) {
    return String(s).replace(RE_LSTRIP, '').replace(RE_RSTRIP, '');
  }

  var RE_PY_FLOAT = /^[+-]?(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/;
  var RE_PY_SPECIAL = /^([+-]?)(inf|infinity|nan)$/i;

  // Python float(str): surrounding whitespace allowed, underscores between
  // digits allowed, inf/nan accepted, anything else raises ValueError.
  function pyFloat(s) {
    var t = pyStrip(s);
    var sp = RE_PY_SPECIAL.exec(t);
    if (sp) {
      if (sp[2].toLowerCase() === 'nan') return NaN;
      return sp[1] === '-' ? -Infinity : Infinity;
    }
    if (!RE_PY_FLOAT.test(t)) {
      throw PyValueError('could not convert string to float: ' + pyRepr(String(s)));
    }
    return Number(t.replace(/_/g, ''));
  }

  // Python round(x) for a float: round half to even, on the exact double.
  function pyRound(x) {
    if (x !== x) throw PyValueError('cannot convert float NaN to integer');
    if (x === Infinity || x === -Infinity) throw PyValueError('cannot convert float infinity to integer');
    var f = Math.floor(x);
    var d = x - f;               // exact for |x| < 2**52
    if (d < 0.5) return f;
    if (d > 0.5) return f + 1;
    return (f % 2 === 0) ? f : f + 1;
  }

  // Python str ordering: lexicographic by code point.
  function cmpCodePoints(a, b) {
    var i = 0, j = 0;
    while (i < a.length && j < b.length) {
      var ca = a.codePointAt(i), cb = b.codePointAt(j);
      if (ca !== cb) return ca < cb ? -1 : 1;
      i += ca > 0xffff ? 2 : 1;
      j += cb > 0xffff ? 2 : 1;
    }
    if (i < a.length) return 1;
    if (j < b.length) return -1;
    return 0;
  }

  function pySorted(iterable) {
    return Array.from(iterable).sort(cmpCodePoints);
  }

  // Python repr() of a str, for the warning text. Covers quote choice and
  // ASCII/Latin-1 control escapes; other non-printable Unicode (which Python
  // would also escape) is passed through. Display text only, not in any
  // golden output.
  function pyRepr(s) {
    var quote = (s.indexOf("'") !== -1 && s.indexOf('"') === -1) ? '"' : "'";
    var out = '';
    for (var k = 0; k < s.length; k++) {
      var ch = s[k], c = s.charCodeAt(k);
      if (ch === '\\') out += '\\\\';
      else if (ch === quote) out += '\\' + quote;
      else if (ch === '\n') out += '\\n';
      else if (ch === '\r') out += '\\r';
      else if (ch === '\t') out += '\\t';
      else if (c < 0x20 || (c >= 0x7f && c <= 0xa0) || c === 0xad) {
        out += '\\x' + (c < 16 ? '0' : '') + c.toString(16);
      } else out += ch;
    }
    return quote + out + quote;
  }

  // Python text-mode readlines(): split on \r\n, \r or \n. The terminator is
  // dropped (every consumer strips or regex-matches up to it anyway).
  function splitLines(text) {
    if (text === '') return [];
    var parts = String(text).split(/\r\n|\r|\n/);
    if (parts.length && parts[parts.length - 1] === '') parts.pop();
    return parts;
  }

  // Decode file bytes the way open(encoding='utf-8', errors='replace') does:
  // a BOM is kept as U+FEFF, invalid bytes become U+FFFD.
  function decodeBytes(bytes) {
    return new TextDecoder('utf-8', { ignoreBOM: true, fatal: false }).decode(bytes);
  }

  // ── Port of cotd_parser.py ─────────────────────────────────────────

  function timeToMs(raw) {
    if (raw === null || raw === undefined || raw === 'DNF' || (typeof raw === 'number' && Number.isInteger(raw))) {
      return raw === undefined ? null : raw;
    }
    return pyRound(pyFloat(String(raw).split(',').join('.')) * 1000);
  }

  function filterTrackerLines(lines) {
    var out = [];
    for (var k = 0; k < lines.length; k++) if (lines[k].indexOf(TRACKER_TAG) !== -1) out.push(lines[k]);
    return out;
  }

  function splitRounds(trackerLines) {
    var rounds = [];
    var current = [];
    for (var k = 0; k < trackerLines.length; k++) {
      var line = trackerLines[k];
      if (line.indexOf('Doing eliminations with leaderboard') !== -1) {
        if (current.length) rounds.push(current);
        current = [];
      } else if (line.indexOf('Eliminating ') !== -1 || line.indexOf('Player ') !== -1) {
        current.push(line);
      }
    }
    if (current.length) rounds.push(current);
    return rounds;
  }

  function reEscape(s) {
    return s.replace(/[.*+?^${}()|[\]\\\/-]/g, '\\$&');
  }

  // Every name the tracker ever printed a time for, code-point sorted.
  // Not in the Python module: submit.html uses it for the mapper and
  // exclusion pickers. Same regex as all_named in parse_cup_log.
  function namedPlayers(lines) {
    var rounds = splitRounds(filterTrackerLines(lines));
    var named = new Set();
    for (var r = 0; r < rounds.length; r++) {
      for (var k = 0; k < rounds[r].length; k++) {
        var m = RE_PLAYER_NAMED.exec(rounds[r][k]);
        if (m) named.add(pyStrip(m[1]));
      }
    }
    return pySorted(named);
  }

  function parseCupLog(lines, excluded) {
    excluded = new Set(excluded || []);
    lines = filterTrackerLines(lines);
    if (!lines.length) throw ParseError('No COTDTracker lines found in log file.');

    var rounds = splitRounds(lines);
    if (!rounds.length) throw ParseError('No elimination rounds found in log.');

    var cup = {
      leaderboard: [], candidates: [], winner: null,
      winnerTimeRaw: null, winnerTimeMs: null,
      fastestTime: null, fastestName: null, fastestRound: null,
      nRounds: rounds.length, warnings: [], ambiguous: false,
    };

    // Elimination order: [name, elimRoundTime, actualRound, dnf]
    var elimOrder = [];
    var actualRound = 0;
    var r, k, m, name;
    for (r = 0; r < rounds.length; r++) {
      var rnd = rounds[r];
      var playerTimes = new Map();
      var eliminatedNames = [];
      for (k = 0; k < rnd.length; k++) {
        m = RE_PLAYER_TIME.exec(rnd[k]);
        if (m) playerTimes.set(pyStrip(m[1]), pyStrip(m[2]));
        var m2 = RE_ELIMINATED.exec(rnd[k]);
        if (m2) {
          name = pyStrip(m2[1]);
          if (eliminatedNames.indexOf(name) === -1) eliminatedNames.push(name);
        }
      }
      if (!eliminatedNames.length) continue;
      actualRound += 1;
      for (k = 0; k < eliminatedNames.length; k++) {
        name = eliminatedNames[k];
        if (!excluded.has(name)) {
          var t = playerTimes.has(name) ? playerTimes.get(name) : 'DNF';
          elimOrder.push([name, t, actualRound, t === 'DNF']);
        }
      }
    }

    var allNamed = new Set();
    for (r = 0; r < rounds.length; r++) {
      for (k = 0; k < rounds[r].length; k++) {
        m = RE_PLAYER_NAMED.exec(rounds[r][k]);
        if (m) allNamed.add(pyStrip(m[1]));
      }
    }

    var sortedExcluded = pySorted(excluded);
    for (k = 0; k < sortedExcluded.length; k++) {
      if (!allNamed.has(sortedExcluded[k])) {
        cup.warnings.push('excluded name ' + pyRepr(sortedExcluded[k]) + ' not found in the log \u2014 ' +
          "either they didn't play, or this isn't their exact raw in-game name.");
      }
    }

    var elimSet = new Set(elimOrder.map(function (e) { return e[0]; }));
    cup.candidates = pySorted(Array.from(allNamed).filter(function (n) {
      return !elimSet.has(n) && !excluded.has(n);
    }));
    cup.ambiguous = cup.candidates.length > 1;
    if (cup.candidates.length !== 1) return cup;
    var winner = cup.candidates[0];
    cup.winner = winner;

    var winnerTime = null;
    var pat = new RegExp('Player ' + reEscape(winner) + ': Time: ([^\\n]+)');
    for (k = lines.length - 1; k >= 0; k--) {
      m = pat.exec(lines[k]);
      if (m) { winnerTime = pyStrip(m[1]); break; }
    }
    cup.winnerTimeRaw = winnerTime;
    cup.winnerTimeMs = timeToMs(winnerTime);

    elimOrder.reverse();
    var leaderboard = [player(winner, winnerTime, null, 1)];
    var pos = 2;
    var i = 0;
    while (i < elimOrder.length) {
      var rn = elimOrder[i][2];
      var group = [];
      while (i < elimOrder.length && elimOrder[i][2] === rn) { group.push(elimOrder[i]); i += 1; }
      var finishers = [];
      var dnfs = [];
      for (k = 0; k < group.length; k++) {
        var g = group[k];
        if (g[3]) {
          dnfs.push(g);
        } else {
          try {
            finishers.push([g[0], g[1], g[2], pyFloat(String(g[1]).split(',').join('.'))]);
          } catch (e) {
            if (!(e instanceof PyValueError)) throw e;
            dnfs.push(g);
          }
        }
      }
      finishers.sort(function (a, b) { return a[3] < b[3] ? -1 : (a[3] > b[3] ? 1 : 0); });
      for (k = 0; k < finishers.length; k++) {
        leaderboard.push(player(finishers[k][0], finishers[k][1], finishers[k][2], pos));
        pos += 1;
      }
      if (dnfs.length) {
        var dnfPos = pos;
        for (k = 0; k < dnfs.length; k++) leaderboard.push(player(dnfs[k][0], dnfs[k][1], dnfs[k][2], dnfPos));
        pos += dnfs.length;
      }
    }
    cup.leaderboard = leaderboard;

    // Fastest time over every leaderboard, warmup included (round 0).
    // Quirks kept: exclusions are not applied, and a non-numeric token other
    // than 'DNF' raises, as in Python.
    var fastestTime = null, fastestName = null, fastestRound = null;
    actualRound = 0;
    for (r = 0; r < rounds.length; r++) {
      var hasElim = rounds[r].some(function (line) { return RE_HAS_ELIM.test(line); });
      if (hasElim) actualRound += 1;
      var rndNum = hasElim ? actualRound : 0;
      for (k = 0; k < rounds[r].length; k++) {
        m = RE_PLAYER_TIME.exec(rounds[r][k]);
        if (m) {
          var nm = pyStrip(m[1]);
          var ts = pyStrip(m[2]);
          if (ts !== 'DNF') {
            var tv = pyFloat(ts.split(',').join('.'));
            if (fastestTime === null || tv < fastestTime) {
              fastestTime = tv; fastestName = nm; fastestRound = rndNum;
            }
          }
        }
      }
    }
    cup.fastestTime = fastestTime;
    cup.fastestName = fastestName;
    cup.fastestRound = fastestRound;
    return cup;
  }

  function player(name, timeRaw, round, pos) {
    return { name: name, timeRaw: timeRaw, round: round, pos: pos, timeMs: timeToMs(timeRaw) };
  }

  function parseCupText(text, excluded) {
    return parseCupLog(splitLines(text), excluded);
  }

  // The cup_<N>.json document. Key order matters: JSON.stringify(payload,
  // null, 2) must equal json.dumps(payload, indent=2, ensure_ascii=False).
  function cupJsonPayload(parsed, cupNum, mapper) {
    return {
      cup: 'COTD ' + cupNum,
      cup_num: cupNum,
      mapper: mapper,
      players: parsed.leaderboard.map(function (p) {
        return { pos: p.pos, name: p.name, time: p.timeMs, round: p.round };
      }),
    };
  }

  return {
    TRACKER_TAG: TRACKER_TAG,
    ParseError: ParseError,
    PyValueError: PyValueError,
    timeToMs: timeToMs,
    splitLines: splitLines,
    decodeBytes: decodeBytes,
    filterTrackerLines: filterTrackerLines,
    splitRounds: splitRounds,
    namedPlayers: namedPlayers,
    parseCupLog: parseCupLog,
    parseCupText: parseCupText,
    cupJsonPayload: cupJsonPayload,
    pyRound: pyRound,
    pyStrip: pyStrip,
    pyFloat: pyFloat,
    pyRepr: pyRepr,
    cmpCodePoints: cmpCodePoints,
  };
});
