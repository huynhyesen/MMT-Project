from agent import monitor


def test_application_time_requires_the_same_foreground_app():
    assert monitor.elapsed_foreground_seconds(None, "Paint", 5.1, 5) == 0
    assert monitor.elapsed_foreground_seconds("Paint", "Notepad", 5.1, 5) == 0
    assert monitor.elapsed_foreground_seconds("Paint", None, 5.1, 5) == 0
    assert monitor.elapsed_foreground_seconds("Paint", "Paint", 25, 5) == 0
    assert monitor.elapsed_foreground_seconds("Paint", "Paint", 5.1, 5) == 5


def test_browsers_and_system_processes_are_not_counted_as_apps():
    assert monitor.tracked_app("msedge.exe") is None
    assert monitor.tracked_app("google-chrome-stable") is None
    assert monitor.tracked_app("LockApp.exe") is None
    assert monitor.tracked_app("kworker/u9:0") is None
    assert monitor.tracked_app("Photoshop.exe") == "Photoshop.exe"


def test_linux_foreground_lookup_uses_active_window_and_idle_time(monkeypatch):
    monkeypatch.setattr(monitor.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    calls = []
    answers = iter(["12\n", "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0123456", "_NET_WM_PID(CARDINAL) = 42"])

    def run(command, **kwargs):
        calls.append(command)
        return next(answers)

    monkeypatch.setattr(monitor.subprocess, "check_output", run)
    assert monitor.foreground_pid() == 42
    assert calls == [["xprintidle"], ["xprop", "-root", "_NET_ACTIVE_WINDOW"], ["xprop", "-id", "0x0123456", "_NET_WM_PID"]]

    answers = iter(["60000\n"])
    assert monitor.foreground_pid() is None
    assert calls[-1] == ["xprintidle"]


def test_windows_foreground_lookup_skips_idle_or_unavailable_windows(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(monitor.sys, "platform", "win32")
    api = SimpleNamespace(GetTickCount=lambda: 100000, GetLastInputInfo=lambda: 99990)
    gui = SimpleNamespace(GetForegroundWindow=lambda: 12)
    monkeypatch.setitem(monitor.sys.modules, "pywintypes", SimpleNamespace(error=OSError))
    monkeypatch.setitem(monitor.sys.modules, "win32api", api)
    monkeypatch.setitem(monitor.sys.modules, "win32gui", gui)
    monkeypatch.setitem(monitor.sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda _: (13, 42)))

    assert monitor.foreground_pid() == 42
    api.GetLastInputInfo = lambda: 40000
    assert monitor.foreground_pid() is None
    api.GetLastInputInfo = lambda: 99990
    gui.GetForegroundWindow = lambda: 0
    assert monitor.foreground_pid() is None
