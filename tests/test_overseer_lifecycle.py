"""Bringing the overseer up from *nothing*.

The Slack bot is now the only controller, so "restart" is not enough: if the
launchd job is unloaded — or its plist is gone from ~/Library/LaunchAgents
entirely — the bot must still be able to start trading again. `launchctl
kickstart` cannot do that; it fails with "Could not find service ... in domain"
(exit 113) because there is no job to kick.

So start reinstalls the plist from the repo copy (the canonical,
version-controlled one) and bootstraps it, and restart falls back to start when
nothing is loaded.
"""
import pytest

from bot.tools import overseer

ADMIN = "U02DQJ9KKFZ"


@pytest.fixture
def cmds(monkeypatch, tmp_path):
    """Record launchctl invocations; pretend the job is not loaded."""
    calls = []
    state = {"loaded": False, "bootstrap_ok": True}

    def fake_run(argv, timeout=None):
        calls.append(list(argv))
        if argv[:2] == ["launchctl", "list"]:
            return state["loaded"], "" if state["loaded"] else "Could not find service"
        if argv[1] == "bootstrap":
            if state["bootstrap_ok"]:
                state["loaded"] = True
                return True, ""
            return False, "Bootstrap failed: 5: Input/output error"
        if argv[1] == "bootout":
            state["loaded"] = False
            return True, ""
        if argv[1] == "kickstart":
            if not state["loaded"]:
                return False, "Could not find service in domain for user gui: 501"
            return True, ""
        return True, ""

    monkeypatch.setattr(overseer, "_run", fake_run)
    monkeypatch.setattr(overseer, "PLIST_DST", tmp_path / "com.goldfinger.overseer.plist")
    src_dir = tmp_path / "schwab"
    src_dir.mkdir()
    (src_dir / "com.goldfinger.overseer.plist").write_text("<plist/>")
    monkeypatch.setattr(overseer.settings, "goldfinger_repo", tmp_path)
    return calls, state


def test_start_installs_the_plist_when_it_is_missing(cmds):
    calls, _ = cmds
    assert not overseer.PLIST_DST.exists()

    ok, msg = overseer.execute_start()

    assert ok, msg
    assert overseer.PLIST_DST.exists(), "plist must be restored from the repo copy"
    assert "reinstalled" in msg


def test_start_bootstraps_the_job(cmds):
    calls, state = cmds
    ok, _ = overseer.execute_start()
    assert ok
    assert any(c[1] == "bootstrap" for c in calls)
    assert state["loaded"]


def test_start_verifies_the_job_is_actually_listed(cmds, monkeypatch):
    """A bootstrap that returns 0 but leaves nothing running must not be
    reported as success — that is how you think trading resumed when it did
    not."""
    calls, state = cmds

    def lying_run(argv, timeout=None):
        calls.append(list(argv))
        if argv[:2] == ["launchctl", "list"]:
            return False, "not loaded"
        return True, ""

    monkeypatch.setattr(overseer, "_run", lying_run)
    ok, msg = overseer.execute_start()
    assert not ok
    assert "not listed" in msg.lower()


def test_start_reports_a_failed_bootstrap(cmds):
    calls, state = cmds
    state["bootstrap_ok"] = False
    ok, msg = overseer.execute_start()
    assert not ok
    assert "Input/output error" in msg


def test_start_is_idempotent_when_already_running(cmds):
    calls, state = cmds
    state["loaded"] = True
    ok, msg = overseer.execute_start()
    assert ok, msg


def test_start_fails_clearly_when_the_repo_plist_is_missing(cmds, monkeypatch, tmp_path):
    calls, _ = cmds
    (tmp_path / "schwab" / "com.goldfinger.overseer.plist").unlink()
    ok, msg = overseer.execute_start()
    assert not ok
    assert "plist" in msg.lower()


def test_restart_falls_back_to_start_when_nothing_is_loaded(cmds):
    """The whole point: `kickstart` on a dead job errors. Restart must not
    simply relay that failure and leave trading down."""
    calls, state = cmds
    state["loaded"] = False

    ok, msg = overseer.execute_restart()

    assert ok, msg
    assert state["loaded"], "restart from dead must leave the overseer running"
    assert any(c[1] == "bootstrap" for c in calls)


def test_restart_uses_kickstart_when_already_loaded(cmds):
    calls, state = cmds
    state["loaded"] = True

    ok, _ = overseer.execute_restart()

    assert ok
    assert any(c[1] == "kickstart" for c in calls)
    assert not any(c[1] == "bootstrap" for c in calls), \
        "a loaded job should be kickstarted, not re-bootstrapped"


def test_stop_unloads_the_job(cmds):
    calls, state = cmds
    state["loaded"] = True

    ok, _ = overseer.execute_stop()

    assert ok
    assert any(c[1] == "bootout" for c in calls)
    assert not state["loaded"]


def test_every_lifecycle_action_has_an_executor():
    """A tool that posts an approval button with no executor behind it would
    look like it worked and do nothing."""
    from bot import app as botapp

    for action in ("start", "stop", "restart"):
        assert action in botapp.EXECUTORS
