import os
import re
import subprocess
import sys

import psutil

BROWSER_PROCESSES = {
    "chrome", "chromium", "chromium-browser", "msedge", "microsoft-edge", "firefox",
    "brave", "brave-browser", "opera", "vivaldi", "coccoc", "browser",
    "google-chrome", "google-chrome-stable", "microsoft-edge-stable", "firefox-esr",
}

IGNORE_SYSTEM_PROCS = {
    "system", "registry", "svchost.exe", "systemd", "kworker", "dbus-daemon",
    "pipewire", "pulseaudio", "xorg", "gnome-shell", "bash", "python3", "python",
    "kthreadd", "pool_workqueue", "rcu_", "irq/", "ksoftirqd", "migration"
}

SCREEN_LOCK_PROCESSES = {"lockapp", "logonui", "winlogon", "xscreensaver", "xsecurelock", "light-locker"}
KERNEL_PROCESS_PREFIXES = ("kworker", "rcu_", "irq/", "ksoftirqd", "migration")


def tracked_app(app_name):
    if not app_name:
        return None
    name = app_name.lower().removesuffix(".exe")
    if (name in BROWSER_PROCESSES or name in IGNORE_SYSTEM_PROCS or name in SCREEN_LOCK_PROCESSES
            or name.startswith(KERNEL_PROCESS_PREFIXES)):
        return None
    return app_name


def get_active_app_metadata():
    """List running processes for enforcement; these entries do not measure elapsed usage."""
    active_apps = []
    seen = set()
    for proc in psutil.process_iter(['name']):
        try:
            p_name = proc.info.get('name')
            if p_name and p_name not in seen:
                seen.add(p_name)
                active_apps.append({
                    "app_name": p_name,
                    "domain": None,  # Nếu là trình duyệt, chỉ lọc tên miền (domain) an toàn
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return active_apps



def foreground_pid(max_idle_ms=60_000):
    """Identify a recently used foreground window in the interactive desktop."""
    if sys.platform == "win32":
        try:
            import pywintypes
            import win32api
            import win32gui
            import win32process
        except ImportError:
            return None
        try:
            elapsed = (win32api.GetTickCount() - win32api.GetLastInputInfo()) & 0xFFFFFFFF
            hwnd = win32gui.GetForegroundWindow()
            if hwnd and elapsed < max_idle_ms:
                return win32process.GetWindowThreadProcessId(hwnd)[1]
        except (OSError, pywintypes.error):
            return None
        return None

    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        return None
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return None
    try:
        idle = subprocess.check_output(["xprintidle"], text=True, timeout=1, stderr=subprocess.DEVNULL)
        if int(idle.strip()) >= max_idle_ms:
            return None
        active = subprocess.check_output(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"], text=True, timeout=1, stderr=subprocess.DEVNULL,
        )
        window = re.search(r"window id # (0x[0-9a-fA-F]+)", active)
        if window and int(window[1], 16):
            owner = subprocess.check_output(
                ["xprop", "-id", window[1], "_NET_WM_PID"], text=True, timeout=1, stderr=subprocess.DEVNULL,
            )
            pid = re.search(r"= ([0-9]+)", owner)
            if pid:
                return int(pid[1])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def get_foreground_app():
    pid = foreground_pid()
    if not pid:
        return None
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def elapsed_foreground_seconds(previous, current, elapsed, poll_interval):
    """Count only intervals bracketed by two observations of the same app."""
    if not current or current != previous or elapsed >= 2 * poll_interval:
        return 0
    return min(poll_interval, max(0, int(elapsed)))
