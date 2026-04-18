DEBUG_MODE = True
ENABLE_MINIMAP = True

Size = 300
LowZoom = 1.2
HightZoom = 0.8

MAX_DISTANCE = 500

Follow_Head = True
Follow_Head_Speed = 750
Follow_Head_Angle_Scale = 500 
Follow_Head_OnScreenTanMax = 0.15
Follow_Head_ScreenMatchScale = 1.0 

Y_Distance = True

import sys
import os
import traceback
import json
from ctypes import *
from ctypes.wintypes import DWORD, LONG, BYTE, HMODULE
from struct import unpack, pack
from math import sqrt, atan2, hypot, isinf
from time import time, sleep
from threading import Thread
from psutil import Process, HIGH_PRIORITY_CLASS, process_iter, NoSuchProcess
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QFont

if not DEBUG_MODE:
    hwnd = windll.kernel32.GetConsoleWindow()
    if hwnd:
        windll.user32.ShowWindow(hwnd, 0)

PROCESS_VM_READ     = 0x0010
PROCESS_QUERY_INFO  = 0x0400
TH32CS_SNAPPROCESS  = 0x00000002
TH32CS_SNAPMODULE   = 0x00000008 | 0x00000010
GWL_EXSTYLE         = -20
WS_EX_LAYERED       = 0x80000
WS_EX_TRANSPARENT   = 0x20
HWND_TOPMOST        = -1
SWP_NOMOVE          = 0x0002
SWP_NOSIZE          = 0x0001
MOUSEEVENTF_MOVE    = 0x0001

class PROCESSENTRY32(Structure):
    _fields_ = [
        ("dwSize",           DWORD),
        ("cntUsage",         DWORD),
        ("th32ProcessID",    DWORD),
        ("th32DefaultHeapID",c_void_p),
        ("th32ModuleID",     DWORD),
        ("cntThreads",       DWORD),
        ("th32ParentProcessID", DWORD),
        ("pcPriClassBase",   c_ulong),
        ("dwFlags",          DWORD),
        ("szExeFile",        c_wchar * 260),
    ]

class MODULEENTRY32(Structure):
    _fields_ = [
        ("dwSize",       DWORD),
        ("th32ModuleID", DWORD),
        ("th32ProcessID",DWORD),
        ("GlblcntUsage", DWORD),
        ("ProccntUsage", DWORD),
        ("modBaseAddr",  c_void_p),
        ("modBaseSize",  DWORD),
        ("hModule",      HMODULE),
        ("szModule",     c_char * 256),
        ("szExePath",    c_char * 260),
    ]

class RECT(Structure):
    _fields_ = [('left', LONG), ('top', LONG), ('right', LONG), ('bottom', LONG)]

class POINT(Structure):
    _fields_ = [('x', LONG), ('y', LONG)]

class Memory:
    def __init__(self):
        self.process_handle = None
        self.process_id     = 0
        self.base_address   = 0

    def _is_valid_ptr(self, address):
        """[STEALTH] Verifica se o ponteiro é plausível antes de tentar lê-lo."""
        return isinstance(address, int) and 0x10000 < address < 0x7FFFFFFFFFFF

    def get_pid_by_name(self, process_name):
        try:
            for proc in process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                        log(f'[+] Process found: {proc.info["name"]} (PID: {proc.info["pid"]})')
                        return proc.info['pid']
                except:
                    continue
        except Exception as e:
            log(f'[!] Error searching for process: {e}')

        try:
            snapshot = windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snapshot == -1:
                return None
            entry = PROCESSENTRY32()
            entry.dwSize = sizeof(PROCESSENTRY32)
            if windll.kernel32.Process32FirstW(snapshot, byref(entry)):
                while True:
                    try:
                        if entry.szExeFile.lower() == process_name.lower():
                            pid = entry.th32ProcessID
                            windll.kernel32.CloseHandle(snapshot)
                            log(f'[+] Process found: {entry.szExeFile} (PID: {pid})')
                            return pid
                    except:
                        pass
                    if not windll.kernel32.Process32NextW(snapshot, byref(entry)):
                        break
            windll.kernel32.CloseHandle(snapshot)
        except Exception as e:
            log(f'[!] Error: {e}')
        return None

    def open_process(self, pid):
        try:
            self.process_id     = pid
            self.process_handle = windll.kernel32.OpenProcess(
                PROCESS_VM_READ | PROCESS_QUERY_INFO, False, pid
            )
            if self.process_handle and self.process_handle != 0:
                log(f'[+] Process opened! Handle: {self.process_handle}')
                return True
            log(f'[!] Failed to open process. Error: {windll.kernel32.GetLastError()}')
            log('[!] Run as Administrator!')
            return False
        except Exception as e:
            log(f'[!] Exception: {e}')
            return False

    def get_module_base(self, module_name="RobloxPlayerBeta.exe"):
        try:
            snapshot = windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, self.process_id)
            if snapshot == -1:
                return 0
            entry = MODULEENTRY32()
            entry.dwSize = sizeof(MODULEENTRY32)
            if windll.kernel32.Module32First(snapshot, byref(entry)):
                while True:
                    try:
                        mod_name = entry.szModule.decode('utf-8', errors='ignore')
                        if mod_name.lower() == module_name.lower():
                            base = entry.modBaseAddr
                            windll.kernel32.CloseHandle(snapshot)
                            log(f'[+] Module {mod_name} - Base: {hex(base)}')
                            return base
                    except:
                        pass
                    if not windll.kernel32.Module32Next(snapshot, byref(entry)):
                        break
            windll.kernel32.CloseHandle(snapshot)
        except Exception as e:
            log(f'[!] Error: {e}')
        return 0

    def read(self, address, size):
        if not self.process_handle or not self._is_valid_ptr(address):
            return b'\x00' * size
        try:
            buffer    = (BYTE * size)()
            bytes_read = c_size_t(0)
            if windll.kernel32.ReadProcessMemory(self.process_handle, c_void_p(address), buffer, size, byref(bytes_read)):
                return bytes(buffer)
        except Exception:
            pass
        return b'\x00' * size

    def write(self, address, data):
        if not self.process_handle or not self._is_valid_ptr(address):
            return False
        buffer        = (BYTE * len(data)).from_buffer_copy(data)
        bytes_written = c_size_t(0)
        return windll.kernel32.WriteProcessMemory(self.process_handle, c_void_p(address), buffer, len(data), byref(bytes_written))

    def read_int8(self, address):
        if not self._is_valid_ptr(address):
            return 0
        data = self.read(address, 8)
        return unpack("<Q", data)[0] if len(data) == 8 else 0

    def read_int4(self, address):
        if not self._is_valid_ptr(address):
            return 0
        data = self.read(address, 4)
        return unpack("<I", data)[0] if len(data) == 4 else 0

    def read_float(self, address):
        if not self._is_valid_ptr(address):
            return 0.0
        data = self.read(address, 4)
        return unpack("<f", data)[0] if len(data) == 4 else 0.0

    def close(self):
        if self.process_handle:
            windll.kernel32.CloseHandle(self.process_handle)

mem              = Memory()
workspaceAddr    = 0
features_enabled = False
offsets         = {}
offsets_ready   = False
minimap_high_zoom = False
follow_head_locked_inst = 0
follow_head_runtime_enabled = Follow_Head

def log(msg):
    if DEBUG_MODE:
        print(msg)

def _offsets_file_path():
    return os.path.join(os.path.dirname(__file__), "Update", "Offsets.py")

def _read_local_offsets_file():
    path = _offsets_file_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _get_nested(dct, *keys):
    cur = dct
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur

def _build_offsets_flat(local_offsets_json):
    """
    Convert the nested Offsets.py JSON into the flat dict `Main.py` expects.
    All offsets are treated as DECIMAL integers (no hex parsing).
    """
    off = local_offsets_json.get("Offsets", {}) if isinstance(local_offsets_json, dict) else {}

    mapped = {
        "FakeDataModelPointer": _get_nested(off, "FakeDataModel", "Pointer"),
        "FakeDataModelToDataModel": _get_nested(off, "FakeDataModel", "RealDataModel"),
        "Workspace": _get_nested(off, "DataModel", "Workspace"),

        "Name": _get_nested(off, "Instance", "Name"),
        "Children": _get_nested(off, "Instance", "ChildrenStart"),
        "Parent": _get_nested(off, "Instance", "Parent"),

        "Primitive": _get_nested(off, "BasePart", "Primitive"),
        "Transparency": _get_nested(off, "BasePart", "Transparency"),
        "Position": _get_nested(off, "Primitive", "Position"),

        "CFrame": _get_nested(off, "Primitive", "Rotation"),
    }

    missing = [k for k, v in mapped.items() if not isinstance(v, int)]
    if missing:
        raise KeyError(f"Missing required offsets in Offsets.py: {', '.join(missing)}")

    return mapped

def get_roblox_version(pid):
    try:
        exe_path = Process(pid).exe()
        folder   = os.path.basename(os.path.dirname(exe_path))
        if folder.startswith("version-"):
            return folder
    except Exception as e:
        log(f'[!] Could not read Roblox exe path: {e}')
    return None

def check_version(pid):
    local_version = get_roblox_version(pid)
    if not local_version:
        print('[!] Version check skipped — could not determine Roblox version.')
        return True

    try:
        offsets_json = _read_local_offsets_file()
        offsets_version = str(offsets_json.get("Roblox Version", "")).strip()
    except Exception as e:
        print(f'[!] Version check skipped — could not read local Offsets.py: {e}')
        return True

    print('----------------------------------------------')
    print(f'  Roblox version   : {local_version}')
    print(f'  Offsets version  : {offsets_version or "UNKNOWN"}')
    if offsets_version and local_version == offsets_version:
        print('  Status           : OK — versions match!')
    else:
        print('  Status           : MISMATCH — offsets may be outdated!')
        print('  The minimap might not work correctly until offsets are updated.')
    print('----------------------------------------------')

    return (not offsets_version) or (local_version == offsets_version)

def read_roblox_string(address):
    try:
        raw_count = mem.read_int4(address + 0x10)
        string_count = min(max(0, raw_count), 128)
        if string_count == 0:
            return ""
        if raw_count > 15:
            ptr  = mem.read_int8(address)
            if not mem._is_valid_ptr(ptr):
                return ""
            data = mem.read(ptr, string_count)
        else:
            data = mem.read(address, string_count)
        return data.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    except Exception:
        return ""

def get_class_name(instance):
    try:
        ptr = mem.read_int8(instance + 0x18)
        ptr = mem.read_int8(ptr + 0x8)
        fl  = mem.read_int8(ptr + 0x18)
        if fl == 0x1F:
            ptr = mem.read_int8(ptr)
        return read_roblox_string(ptr)
    except:
        return ""

def get_name(instance, name_offset):
    try:
        ptr = mem.read_int8(instance + name_offset)
        return read_roblox_string(ptr)
    except:
        return ""

def get_children(instance, children_offset):
    try:
        children_start = mem.read_int8(instance + children_offset)
        if not children_start:
            return []
        children_end = mem.read_int8(children_start + 8)
        current      = mem.read_int8(children_start)
        children     = []
        for _ in range(9000):
            if current == children_end:
                break
            children.append(mem.read_int8(current))
            current += 0x10
        return children
    except:
        return []

def find_first_child(instance, child_name, name_offset, children_offset):
    try:
        for child in get_children(instance, children_offset):
            if get_name(child, name_offset) == child_name:
                return child
    except:
        pass
    return 0

def find_first_child_of_class(instance, class_name, children_offset):
    try:
        for child in get_children(instance, children_offset):
            if get_class_name(child) == class_name:
                return child
    except:
        pass
    return 0

def read_head_transparency(head_inst):
    """Head instance + Transparency offset (treat as invisible/dead when >= 1)."""
    if not head_inst or 'Transparency' not in offsets:
        return 0.0
    try:
        return mem.read_float(head_inst + offsets['Transparency'])
    except Exception:
        return 0.0

def read_vec3_position(primitive_addr):
    """World position from BasePart primitive + Position offset."""
    if not primitive_addr:
        return None
    try:
        raw = mem.read(primitive_addr + offsets['Position'], 12)
        if len(raw) != 12:
            return None
        return unpack("<fff", raw)
    except Exception:
        return None

def read_cframe_rotation_3x3(primitive_addr):
    """
    3x3 rotation (row-major) at Primitive + CFrame.
    Roblox LookVector = -third column = (-r02, -r12, -r22).
    """
    if not primitive_addr or 'CFrame' not in offsets:
        return None
    try:
        raw = mem.read(primitive_addr + offsets['CFrame'], 36)
        if len(raw) != 36:
            return None
        f = unpack("<9f", raw)
        return f
    except Exception:
        return None

def horizontal_forward_from_cframe(rot_9):
    """Project Roblox LookVector onto XZ; return normalized (fx, fz) for minimap 'north'."""
    if not rot_9:
        return None
    r02, r12, r22 = rot_9[2], rot_9[5], rot_9[8]
    lx, lz = -r02, -r22
    hlen = sqrt(lx * lx + lz * lz)
    if hlen < 1e-6:
        return None
    return lx / hlen, lz / hlen

def horizontal_right_from_forward(fx, fz):
    """Right in XZ plane (matches Roblox horizontal basis with forward)."""
    rx, rz = -fz, fx
    hlen = sqrt(rx * rx + rz * rz)
    if hlen < 1e-6:
        return None
    return rx / hlen, rz / hlen

def _vec3_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

def _vec3_normalize(v):
    x, y, z = v
    l = sqrt(x * x + y * y + z * z)
    if l < 1e-9:
        return None
    return (x / l, y / l, z / l)

def _rotation_basis_from_prim(prim_addr):
    """Right, Up, -Look columns from row-major 3x3 at Primitive + CFrame."""
    rot = read_cframe_rotation_3x3(prim_addr)
    if not rot:
        return None, None, None
    r00, r01, r02 = rot[0], rot[1], rot[2]
    r10, r11, r12 = rot[3], rot[4], rot[5]
    r20, r21, r22 = rot[6], rot[7], rot[8]
    right = (r00, r10, r20)
    up = (r01, r11, r21)
    look = (-r02, -r12, -r22)
    return right, up, look

def _head_tan_screen(right, up, look, cam_pos, head_pos):
    """
    Project head direction into normalized tan space vs camera (same units as cursor offset from center).
    Returns (sx, sy) or None if behind camera or too far.
    """
    dxw = head_pos[0] - cam_pos[0]
    dyw = head_pos[1] - cam_pos[1]
    dzw = head_pos[2] - cam_pos[2]
    dist = sqrt(dxw * dxw + dyw * dyw + dzw * dzw)
    if dist > MAX_DISTANCE or dist < 1e-4:
        return None
    dvec = _vec3_normalize((dxw, dyw, dzw))
    if not dvec:
        return None
    dot_f = _vec3_dot(look, dvec)
    if dot_f <= 0.0:
        return None
    dot_r = _vec3_dot(dvec, right)
    dot_u = _vec3_dot(dvec, up)
    sx = dot_r / dot_f
    sy = -dot_u / dot_f
    return sx, sy

def _follow_head_filters_ok(head_inst):
    if not head_inst:
        return False
    try:
        if read_head_transparency(head_inst) >= 1.0:
            return False
        if find_first_child(head_inst, 'Username', offsets['Name'], offsets['Children']):
            return False
        return True
    except Exception:
        return False

def _pick_nearest_head_to_mouse(vmodels, local_vm, cam_pos, right, up, look, mx_n, my_n):
    """
    Valid heads only: in front of camera, roughly on screen (|tan| bound), nearest in 2D to cursor.
    mx_n, my_n: cursor offset from client center in [-1,1]-style units (per half-width/height).
    """
    lim = Follow_Head_OnScreenTanMax
    ms = Follow_Head_ScreenMatchScale
    cands = []

    for vm in get_children(vmodels, offsets['Children']):
        try:
            vm_name = get_name(vm, offsets['Name'])
            if vm == local_vm or vm_name == 'LocalViewmodel':
                continue

            head = find_first_child(vm, 'head', offsets['Name'], offsets['Children'])
            if not head or not _follow_head_filters_ok(head):
                continue

            head_prim = mem.read_int8(head + offsets['Primitive'])
            hp = read_vec3_position(head_prim)
            if not hp:
                continue

            tan = _head_tan_screen(right, up, look, cam_pos, hp)
            if tan is None:
                continue
            sx, sy = tan
            if abs(sx) > lim or abs(sy) > lim:
                continue

            d2 = (sx - mx_n * ms) ** 2 + (sy - my_n * ms) ** 2
            cands.append((d2, head))
        except Exception:
            continue

    cands.sort(key=lambda x: x[0])
    if cands:
        return cands[0][1]
    return 0

def _aim_error_pixels_for_head(head_inst, cam_pos, right, up, look):
    """
    Full relative-mouse correction (px, px) to bring crosshair onto this head (head to screen center).
    """
    try:
        head_prim = mem.read_int8(head_inst + offsets['Primitive'])
        hp = read_vec3_position(head_prim)
        if not hp:
            return 0.0, 0.0
        if not _follow_head_filters_ok(head_inst):
            return 0.0, 0.0

        lx, ly, lz = cam_pos
        dxw = hp[0] - lx
        dyw = hp[1] - ly
        dzw = hp[2] - lz
        dist = sqrt(dxw * dxw + dyw * dyw + dzw * dzw)
        if dist > MAX_DISTANCE or dist < 1e-4:
            return 0.0, 0.0

        dvec = _vec3_normalize((dxw, dyw, dzw))
        if not dvec:
            return 0.0, 0.0
        dot_f = _vec3_dot(look, dvec)
        if dot_f <= 0.0:
            return 0.0, 0.0

        dot_r = _vec3_dot(dvec, right)
        dot_u = _vec3_dot(dvec, up)
        yaw = atan2(dot_r, dot_f)
        pitch = atan2(-dot_u, sqrt(dot_f * dot_f + dot_r * dot_r))
        s = Follow_Head_Angle_Scale
        return yaw * s, pitch * s
    except Exception:
        return 0.0, 0.0

def compute_follow_head_mouse_delta():
    """
    While L is held (caller clears lock when released): lock a head nearest cursor on screen,
    then return the full aim-error vector (px) toward placing that head at screen center.
    """
    global follow_head_locked_inst

    if not follow_head_runtime_enabled or workspaceAddr == 0 or not offsets_ready:
        return 0.0, 0.0
    try:
        hwnd = find_window_by_title("Roblox")
        if not hwnd:
            return 0.0, 0.0

        cur = get_cursor_client_xy(hwnd)
        if cur is None:
            return 0.0, 0.0
        ww, hh = get_client_size(hwnd)
        if ww < 8 or hh < 8:
            return 0.0, 0.0

        cx = ww * 0.5
        cy = hh * 0.5
        mx_n = (cur[0] - cx) / cx
        my_n = (cur[1] - cy) / cy

        waddr = workspaceAddr
        vmodels = find_first_child(waddr, 'Viewmodels', offsets['Name'], offsets['Children'])
        if not vmodels:
            return 0.0, 0.0

        local_vm = find_first_child(vmodels, 'LocalViewmodel', offsets['Name'], offsets['Children'])
        if not local_vm:
            return 0.0, 0.0

        lp_head = find_first_child(local_vm, 'head', offsets['Name'], offsets['Children'])
        if not lp_head:
            return 0.0, 0.0

        lp_prim = mem.read_int8(lp_head + offsets['Primitive'])
        lp_pos = read_vec3_position(lp_prim)
        if not lp_pos:
            return 0.0, 0.0

        basis = _rotation_basis_from_prim(lp_prim)
        right, up, look = basis[0], basis[1], basis[2]
        if not look:
            return 0.0, 0.0

        if follow_head_locked_inst == 0 or not _follow_head_filters_ok(follow_head_locked_inst):
            follow_head_locked_inst = 0
            picked = _pick_nearest_head_to_mouse(
                vmodels, local_vm, lp_pos, right, up, look, mx_n, my_n
            )
            follow_head_locked_inst = picked

        if follow_head_locked_inst == 0:
            return 0.0, 0.0

        hp_prim = mem.read_int8(follow_head_locked_inst + offsets['Primitive'])
        hp_live = read_vec3_position(hp_prim)
        if not hp_live:
            follow_head_locked_inst = 0
            return 0.0, 0.0

        tan = _head_tan_screen(right, up, look, lp_pos, hp_live)
        if tan is None or abs(tan[0]) > Follow_Head_OnScreenTanMax or abs(tan[1]) > Follow_Head_OnScreenTanMax:
            follow_head_locked_inst = 0
            return 0.0, 0.0

        return _aim_error_pixels_for_head(follow_head_locked_inst, lp_pos, right, up, look)
    except Exception:
        return 0.0, 0.0

def world_delta_to_minimap(dx, dz, forward_xz, zoom_px):
    """
    Map world delta (dx, dz) to minimap pixel offset from center.
    Forward = north (up on screen). Right = east (right on screen).
    """
    fx, fz = forward_xz
    rx, rz = horizontal_right_from_forward(fx, fz)
    if rx is None:
        return None
    local_fwd = dx * fx + dz * fz
    local_r = dx * rx + dz * rz
    mx = local_r * zoom_px
    my = -local_fwd * zoom_px
    return mx, my

def find_window_by_title(title):
    return windll.user32.FindWindowW(None, title)

def get_client_rect_on_screen(hwnd):
    rect     = RECT()
    if windll.user32.GetClientRect(hwnd, byref(rect)) == 0:
        return 0, 0, 0, 0
    top_left  = POINT(rect.left, rect.top)
    bot_right = POINT(rect.right, rect.bottom)
    windll.user32.ClientToScreen(hwnd, byref(top_left))
    windll.user32.ClientToScreen(hwnd, byref(bot_right))
    return top_left.x, top_left.y, bot_right.x, bot_right.y

def get_window_rect(hwnd):
    rect = RECT()
    windll.user32.GetWindowRect(hwnd, byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom

def get_client_size(hwnd):
    rect = RECT()
    if windll.user32.GetClientRect(hwnd, byref(rect)) == 0:
        return 0, 0
    return int(rect.right - rect.left), int(rect.bottom - rect.top)

def get_cursor_client_xy(hwnd):
    """Cursor position in client coordinates, or None."""
    pt = POINT()
    if windll.user32.GetCursorPos(byref(pt)) == 0:
        return None
    if windll.user32.ScreenToClient(hwnd, byref(pt)) == 0:
        return None
    return int(pt.x), int(pt.y)

def _load_offsets_async(pid, callback):
    try:
        check_version(pid)
        log('[*] Loading offsets from local Offsets.py (async)...')
        raw = _read_local_offsets_file()
        parsed = _build_offsets_flat(raw)
        log('[+] Offsets loaded successfully!')
        callback(parsed)
    except Exception as e:
        log(f'[!] Error loading offsets: {e}')
        callback(None)

def init_injection():
    global workspaceAddr, offsets, offsets_ready

    while True:
        log('[*] Waiting for Roblox...')

        while True:
            pid = mem.get_pid_by_name("RobloxPlayerBeta.exe")
            if pid and mem.open_process(pid):
                break
            sleep(1)

        offsets_ready = False
        def _on_offsets(result):
            global offsets, offsets_ready
            if result:
                offsets = result
                offsets_ready = True
            else:
                offsets_ready = False

        Thread(target=_load_offsets_async, args=(pid, _on_offsets), daemon=True).start()

        for _ in range(150):
            if offsets_ready:
                break
            sleep(0.1)

        if not offsets_ready:
            log('[!] Offsets not loaded, retrying...')
            sleep(5)
            continue

        try:
            baseAddr = mem.get_module_base()
            if not baseAddr:
                log('[!] Failed to get base address!')
                sleep(5)
                continue

            fakeDatamodel = mem.read_int8(baseAddr + offsets['FakeDataModelPointer'])
            if not fakeDatamodel:
                sleep(5)
                continue

            dataModel = mem.read_int8(fakeDatamodel + offsets['FakeDataModelToDataModel'])
            if not dataModel:
                sleep(5)
                continue

            ws = 0
            for _ in range(30):
                ws = mem.read_int8(dataModel + offsets['Workspace'])
                if ws:
                    break
                sleep(1)

            if not ws:
                sleep(5)
                continue

            workspaceAddr = ws

            log('[+] Injection completed successfully!')
            log(f'[!] Minimap: {"ENABLED" if ENABLE_MINIMAP else "DISABLED"}')
            log(f'[!] Follow_Head: {"ENABLED" if Follow_Head else "DISABLED"} (hold Left Click)')
            log('[!] Press P to toggle | N Low/High zoom | INSERT to quit')
            return True

        except Exception as e:
            log(f'[!] Injection error: {e}')
            log(traceback.format_exc())
            sleep(5)

class MinimapCanvas(QWidget):
    """Blue = LocalViewmodel head at center; points (mx, my, is_ally [, dy])."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(80, 80)
        self._points = []
        self._half = 100
        self._font_label = QFont("Arial", 8)
        self._center_dot_enabled = True

    def set_half_size(self, h):
        self._half = max(40, int(h))
        self.setFixedSize(self._half * 2, self._half * 2)

    def set_points(self, points):
        """points: list of (offset_x, offset_y, is_green) or (... , dy_world)."""
        self._points = points
        self.update()

    def set_center_dot_enabled(self, enabled):
        self._center_dot_enabled = bool(enabled)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self._font_label)
        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        half = min(cx, cy) - 2

        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        pen = QPen(QColor(0, 0, 0, 255))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(cx - half, cy - half, half * 2, half * 2)

        cross_pen = QPen(QColor(0, 0, 0, 140))
        cross_pen.setWidth(1)
        painter.setPen(cross_pen)
        painter.drawLine(cx, cy - half, cx, cy + half)
        painter.drawLine(cx - half, cy, cx + half, cy)

        painter.setPen(Qt.NoPen)
        center_col = QColor(0, 100, 255, 255) if self._center_dot_enabled else QColor(255, 220, 0, 255)
        painter.setBrush(QBrush(center_col))
        painter.drawEllipse(cx - 4, cy - 4, 8, 8)

        for item in self._points:
            if len(item) >= 4:
                mx, my, is_green, dy_w = item[0], item[1], item[2], item[3]
            elif len(item) == 3:
                mx, my, is_green = item
                dy_w = None
            else:
                mx, my = item[0], item[1]
                is_green = False
                dy_w = None
            if abs(mx) > half or abs(my) > half:
                continue
            col = QColor(0, 200, 80, 255) if is_green else QColor(255, 0, 0, 255)
            painter.setBrush(QBrush(col))
            painter.drawEllipse(int(cx + mx - 3), int(cy + my - 3), 6, 6)

            if Y_Distance and dy_w is not None:
                painter.setPen(QPen(QColor(255, 255, 255, 255)))
                painter.setBrush(Qt.NoBrush)
                painter.drawText(
                    int(cx + mx + 5),
                    int(cy + my + 3),
                    f"{dy_w:.1f}",
                )
                painter.setPen(Qt.NoPen)

        painter.end()


class MinimapWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.last_geom_check = 0.0

        half = max(40, int(Size) // 2)
        self.canvas = MinimapCanvas()
        self.canvas.set_half_size(half)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.canvas)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self._tick_interval_ms = 8
        self.timer.start(self._tick_interval_ms)
        self.adjustSize()
        self.show()
        self._place_window()

    def _place_window(self):
        hwnd = find_window_by_title("Roblox")
        if not hwnd:
            return
        x, y, r, b = get_client_rect_on_screen(hwnd)
        ww, hh = r - x, b - y
        if ww <= 0 or hh <= 0:
            x, y, r, b = get_window_rect(hwnd)
            ww, hh = r - x, b - y
        if ww <= 0:
            return
        margin = 12
        self.move(int(x + (ww - self.width()) / 2), y + hh - self.height() - margin)

    def _tick(self):
        now = time()
        if now - self.last_geom_check > 1.5:
            self._place_window()
            self.last_geom_check = now
        self._update_minimap()

    def _update_minimap(self):
        if not ENABLE_MINIMAP or not features_enabled or workspaceAddr == 0:
            self.canvas.set_points([])
            return

        try:
            waddr = workspaceAddr
            vmodels = find_first_child(waddr, 'Viewmodels', offsets['Name'], offsets['Children'])
            if not vmodels:
                self.canvas.set_points([])
                return

            local_vm = find_first_child(vmodels, 'LocalViewmodel', offsets['Name'], offsets['Children'])
            if not local_vm:
                self.canvas.set_points([])
                return

            lp_head = find_first_child(local_vm, 'head', offsets['Name'], offsets['Children'])
            if not lp_head:
                self.canvas.set_points([])
                return

            lp_prim = mem.read_int8(lp_head + offsets['Primitive'])
            lp_pos = read_vec3_position(lp_prim)
            if not lp_pos:
                self.canvas.set_points([])
                return

            rot = read_cframe_rotation_3x3(lp_prim)
            forward_xz = horizontal_forward_from_cframe(rot)
            if forward_xz is None:
                forward_xz = (0.0, 1.0)

            lx, ly, lz = lp_pos
            zoom_px = HightZoom if minimap_high_zoom else LowZoom

            pts = []
            for vm in get_children(vmodels, offsets['Children']):
                try:
                    vm_name = get_name(vm, offsets['Name'])
                    if vm == local_vm or vm_name == 'LocalViewmodel':
                        continue

                    head = find_first_child(vm, 'head', offsets['Name'], offsets['Children'])
                    if not head:
                        continue
                    if read_head_transparency(head) >= 1.0:
                        continue

                    head_prim = mem.read_int8(head + offsets['Primitive']) 
                    hp = read_vec3_position(head_prim)
                    if not hp:
                        continue

                    dx = hp[0] - lx
                    dz = hp[2] - lz
                    dist = sqrt(dx * dx + dz * dz)
                    if dist > MAX_DISTANCE:
                        continue

                    mapped = world_delta_to_minimap(dx, dz, forward_xz, zoom_px)
                    if mapped is None:
                        continue
                    mx, my = mapped
                    team_check = find_first_child(head, 'Username', offsets['Name'], offsets['Children']) != 0
                    dy_delta = hp[1] - ly
                    pts.append((mx, my, team_check, dy_delta))
                except Exception:
                    continue

            self.canvas.set_points(pts)
        except Exception:
            self.canvas.set_points([])

def follow_head_worker():
    """While LeftClick is held, move mouse toward nearest valid head at Follow_Head_Speed."""
    global follow_head_locked_inst
    LMOUSE_KEY = 0x01
    last_t = time()
    while mem.process_id == 0:
        sleep(0.05)

    while True:
        try:
            now = time()
            dt = now - last_t
            last_t = now
            if dt < 0.001:
                dt = 0.001
            if dt > 0.05:
                dt = 0.05

            if not follow_head_runtime_enabled or not features_enabled:
                follow_head_locked_inst = 0
                sleep(0.008)
                continue

            if not (windll.user32.GetAsyncKeyState(LMOUSE_KEY) & 0x8000):
                follow_head_locked_inst = 0
                sleep(0.008)
                continue

            if not isinf(Follow_Head_Speed) and Follow_Head_Speed <= 0:
                follow_head_locked_inst = 0
                sleep(0.008)
                continue

            fdx, fdy = compute_follow_head_mouse_delta()
            if abs(fdx) < 1e-6 and abs(fdy) < 1e-6:
                sleep(0.008)
                continue

            dx, dy = fdx, fdy
            mag = hypot(dx, dy)
            if not isinf(Follow_Head_Speed) and mag > 1e-6:
                max_step = Follow_Head_Speed * dt
                if mag > max_step:
                    s = max_step / mag
                    dx *= s
                    dy *= s

            idx = int(round(dx))
            idy = int(round(dy))
            if idx != 0 or idy != 0:
                windll.user32.mouse_event(MOUSEEVENTF_MOVE, idx, idy, 0, 0)

            sleep(0.008)
        except SystemExit:
            raise
        except Exception:
            sleep(0.016)

def hotkey_listener():
    global features_enabled, minimap_high_zoom, follow_head_runtime_enabled, follow_head_locked_inst
    P_KEY      = 0x50
    N_KEY      = 0x4E
    INSERT_KEY = 0x2D
    MIDDLE_MOUSE_KEY = 0x04
    last_p     = False
    last_n     = False
    last_ins   = False
    last_mid   = False
    check_cnt  = 0

    while mem.process_id == 0:
        sleep(0.1)

    roblox_pid = mem.process_id
    log(f'[+] Hotkey listener started (PID: {roblox_pid})')
    log('[*] P = toggle | N = LowZoom / HightZoom | Left Click = Follow_Head (hold) | INSERT = quit')

    while True:
        try:
            check_cnt += 1
            if check_cnt >= 20:
                check_cnt = 0
                try:
                    proc = Process(roblox_pid)
                    if not proc.is_running():
                        raise NoSuchProcess(roblox_pid)
                except (NoSuchProcess, Exception):
                    log('[!] Roblox was closed - exiting...')
                    sleep(1)
                    sys.exit(0)

            cur_p   = windll.user32.GetAsyncKeyState(P_KEY)      & 0x8000 != 0
            cur_n   = windll.user32.GetAsyncKeyState(N_KEY)      & 0x8000 != 0
            cur_ins = windll.user32.GetAsyncKeyState(INSERT_KEY) & 0x8000 != 0
            cur_mid = windll.user32.GetAsyncKeyState(MIDDLE_MOUSE_KEY) & 0x8000 != 0

            if cur_p and not last_p:
                features_enabled = not features_enabled
                log(f'[*] Features {"ENABLED" if features_enabled else "DISABLED"}')

            if cur_n and not last_n:
                minimap_high_zoom = not minimap_high_zoom
                zl = 'HightZoom' if minimap_high_zoom else 'LowZoom'
                log(f'[*] Minimap zoom: {zl}')

            if cur_mid and not last_mid:
                follow_head_runtime_enabled = not follow_head_runtime_enabled
                if not follow_head_runtime_enabled:
                    follow_head_locked_inst = 0
                log(f'[*] Follow_Head {"ENABLED" if follow_head_runtime_enabled else "DISABLED"}')

            if cur_ins and not last_ins:
                log('[*] INSERT pressed - closing...')
                sys.exit(0)

            last_p   = cur_p
            last_n   = cur_n
            last_ins = cur_ins
            last_mid = cur_mid
        except SystemExit:
            raise
        except:
            pass

        sleep(0.05)

if __name__ == "__main__":
    try:
        Process(os.getpid()).nice(HIGH_PRIORITY_CLASS)
    except:
        pass

    log('================')
    log('     Fuyuma on top')
    log('================')
    log(f'Minimap: {"✓" if ENABLE_MINIMAP else "✗"}')
    log(f'Follow_Head: {"✓" if Follow_Head else "✗"}')
    log('================')

    init_injection()

    Thread(target=hotkey_listener, daemon=True).start()
    Thread(target=follow_head_worker, daemon=True).start()
    log('[+] Follow_Head worker')

    app = QApplication([])

    minimap_win = None
    if ENABLE_MINIMAP:
        minimap_win = MinimapWindow()
        minimap_win.canvas.set_center_dot_enabled(follow_head_runtime_enabled)
        log('[+] Minimap window')

    log('[*] Press P to toggle | N for LowZoom/HightZoom | hold LeftClick for Follow_Head | Middle Click to toggle Follow_Head | INSERT to quit')
    if minimap_win:
        dot_timer = QTimer()
        dot_timer.setTimerType(Qt.PreciseTimer)
        dot_timer.timeout.connect(lambda: minimap_win.canvas.set_center_dot_enabled(follow_head_runtime_enabled))
        dot_timer.start(25)

    sys.exit(app.exec_())
