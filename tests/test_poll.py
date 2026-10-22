"""submissions_poll.py: resends of a processed cup, completion and publish guards."""
import os
from types import SimpleNamespace

import pytest

import submissions_poll as P

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTX = SimpleNamespace(repo=REPO)


def _log(cup):
    return os.path.join(REPO, 'tracker_logs', f'cotd_{cup}.log')


@pytest.mark.parametrize('log,cup,mapper,exclude,agrees,expect', [
    # the same cup sent again, same reading: on record, no flag
    (166, 166, '[SLOW]Zeus', [], True, 'matches the published result'),
    # a ghost cup: the block says "PulchritudinousPlum (elo=Shattersmith)", the log the account name
    (164, 164, 'clycl', [], True, 'matches the published result'),
    # a submitter excluding someone who raced: one player fewer
    (166, 166, '[SLOW]Zeus', ['Jake'], False, '56 players (published 57)'),
    # excluding the winner changes the winner
    (166, 166, '[SLOW]Zeus', ['Kernkob'], False, 'winner'),
    # another cup's log sent under this number
    (165, 166, '[SLOW]Zeus', [], False, 'DIFFERS'),
])
def test_compare_with_published(log, cup, mapper, exclude, agrees, expect):
    sub = {'cup': cup, 'mapper': mapper, 'exclude': exclude}
    ok, note = P.compare_with_published(sub, _log(log), P.published_block(CTX, cup))
    assert ok is agrees, note
    assert expect in note, note


def test_published_block_strips_ghost_tags():
    names = P.published_block(CTX, 164)
    assert 'PulchritudinousPlum' in names
    assert not any('(elo=' in n for n in names)
    assert P.published_block(CTX, 999) is None


def test_complete_is_a_whole_line():
    assert P.is_complete(166, 'x\nCOTD 166 COMPLETE\n')
    assert not P.is_complete(16, 'COTD 166 COMPLETE\n')
    assert not P.is_complete(166, 'echo "COTD 166 COMPLETE" later\n')


@pytest.mark.parametrize('rehearsal,dry_run', [(True, False), (False, True)])
def test_no_pull_request_in_rehearsal_or_dry_run(rehearsal, dry_run):
    ctx = SimpleNamespace(rehearsal=rehearsal, dry_run=dry_run, repo=REPO)
    sub = {'cup': 167, 'map': 'M', 'mapper': 'X'}
    with pytest.raises(RuntimeError, match='publication disabled'):
        P.open_pr(ctx, sub, {})
