import asyncio
import pytest
from unittest.mock import MagicMock, patch
import telegram_bot_service as tbs
import batch_apply_parallel as bap


def test_supervisor_state_transitions():
    tbs.RUNNER_SUPERVISOR_STATE["desired"] = "paused"
    with patch("subprocess.Popen") as mock_popen, \
         patch("telegram_bot_service.get_realtime_metrics") as mock_metrics:
        mock_metrics.return_value = {"unapplied_count": 100, "is_running": False}
        tbs.launch_runner(workers=4, queue="queue_cyber_iam.txt", delay=1.5, user_action=True)
        assert tbs.RUNNER_SUPERVISOR_STATE["desired"] == "running"
        assert tbs.RUNNER_SUPERVISOR_STATE["workers"] == 4
        assert tbs.RUNNER_SUPERVISOR_STATE["delay"] == 1.5
        assert tbs.RUNNER_SUPERVISOR_STATE["queue"] == "queue_cyber_iam.txt"
        
        # Verify --continuous flag was passed
        cmd = mock_popen.call_args[0][0]
        assert "--continuous" in cmd
        assert "--workers" in cmd
        assert "4" in cmd

    with patch("psutil.process_iter", return_value=[]):
        tbs.halt_runner()
        assert tbs.RUNNER_SUPERVISOR_STATE["desired"] == "paused"


def test_watchdog_supervisor_job_restarts_when_idle():
    async def _run():
        tbs.RUNNER_SUPERVISOR_STATE["desired"] = "running"
        tbs.RUNNER_SUPERVISOR_STATE["last_relaunch"] = 0.0
        initial_restarts = tbs.RUNNER_SUPERVISOR_STATE.get("auto_restarts", 0)

        context = MagicMock()
        with patch("telegram_bot_service.get_realtime_metrics") as mock_metrics, \
             patch("telegram_bot_service.launch_runner") as mock_launch:
            # Case 1: Already running -> do nothing
            mock_metrics.return_value = {"is_running": True, "total_applied": 1114, "unapplied_count": 500}
            await tbs.runner_watchdog_supervisor_job(context)
            mock_launch.assert_not_called()

            # Case 2: Idle but desired == running -> auto-relaunch
            mock_metrics.return_value = {"is_running": False, "total_applied": 1114, "unapplied_count": 500}
            await tbs.runner_watchdog_supervisor_job(context)
            mock_launch.assert_called_once()
            assert tbs.RUNNER_SUPERVISOR_STATE["auto_restarts"] == initial_restarts + 1

    asyncio.run(_run())


def test_status_message_reflects_supervisor_state():
    mock_metrics = {
        "total_applied": 1114,
        "today_applied": 40,
        "is_running": False,
        "worker_count": 0,
        "total_mem_mb": 0,
        "current_target": None,
        "queue_count": 500,
        "unapplied_count": 480,
        "pending_questions": [],
        "inbox_actions": [],
        "recent": [],
    }

    # Desired running but idle -> Re-igniting
    tbs.RUNNER_SUPERVISOR_STATE["desired"] = "running"
    msg_reigniting = tbs.format_status_message(metrics=mock_metrics)
    assert "Restarting" in msg_reigniting

    # Desired paused -> Paused
    tbs.RUNNER_SUPERVISOR_STATE["desired"] = "paused"
    msg_paused = tbs.format_status_message(metrics=mock_metrics)
    assert "Paused" in msg_paused

    # Running -> Running
    mock_metrics["is_running"] = True
    mock_metrics["worker_count"] = 3
    msg_running = tbs.format_status_message(metrics=mock_metrics)
    assert "Running" in msg_running
