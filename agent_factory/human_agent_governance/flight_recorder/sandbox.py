"""Linux x86_64 research planner confinement. No silent fallback if controls are unavailable.

Trusted launcher calls confine BEFORE loading planner code. Never run the gateway/recorder inside it.
This is an additional mock boundary; production still requires separate OS identities and reviewed services.
"""

from __future__ import annotations

import ctypes
import errno
import os
import platform
from pathlib import Path

from ..policy import GovernanceError


class _Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int)]


class _Filter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class _Program(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_Filter))]


def confine(read_paths: list[Path], workspace: Path) -> None:
    """Deny host-file reads/writes except explicit runtime paths and a dummy workspace.

    Use a fresh child with close_fds=True, sanitized environment, no credential inheritance and bounded input.
    Input/output pipes must be provided by the trusted host, not passed as filesystem/service capabilities.
    """
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise GovernanceError("Research sandbox requires Linux x86_64")
    libc = ctypes.CDLL(None, use_errno=True)

    def checked(result):
        if result < 0:
            raise GovernanceError(f"Sandbox control unavailable (errno {ctypes.get_errno()})")
        return result

    checked(libc.prctl(38, 1, 0, 0, 0))  # PR_SET_NO_NEW_PRIVS
    abi = checked(libc.syscall(444, 0, 0, 1))
    handled = (1 << 13) - 1
    if abi >= 2:
        handled |= 1 << 13  # REFER
    if abi >= 3:
        handled |= 1 << 14  # TRUNCATE
    if abi >= 5:
        handled |= 1 << 15  # IOCTL_DEV
    ruleset = _Ruleset(handled)
    fd = checked(libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0))
    try:
        for path, access in [(Path(p), 1 | 4 | 8) for p in read_paths] + [(Path(workspace), handled)]:
            parent_fd = os.open(path.resolve(strict=True), os.O_PATH | os.O_CLOEXEC)
            try:
                rule = _PathRule(access, parent_fd)
                checked(libc.syscall(445, fd, 1, ctypes.byref(rule), 0))
            finally:
                os.close(parent_fd)
        checked(libc.syscall(446, fd, 0))
    finally:
        os.close(fd)
    _seccomp(libc, checked)


def _seccomp(libc, checked, *, memory_only=False):
    # Deny network, peer process access/signalling, filesystem namespace escapes and asynchronous I/O escapes.
    denied = {
        41,
        42,
        101,
        62,
        200,
        234,
        310,
        311,
        434,
        438,
        424,
        321,
        298,
        165,
        166,
        155,
        308,
        272,
        304,
        425,
        426,
        427,
        169,
        246,
        320,
    }
    if memory_only:
        # No new file descriptors, path mutations, metadata queries, processes or threads.
        denied.update(
            {
                2,
                257,
                437,
                85,
                87,
                263,
                82,
                264,
                316,
                76,
                77,
                83,
                258,
                84,
                86,
                265,
                88,
                266,
                90,
                91,
                268,
                452,
                92,
                93,
                94,
                260,
                133,
                259,
                4,
                6,
                262,
                332,
                78,
                217,
                89,
                267,
                56,
                57,
                58,
                435,
            }
        )
    instructions = [
        _Filter(0x20, 0, 0, 4),
        _Filter(0x15, 1, 0, 0xC000003E),
        _Filter(0x06, 0, 0, 0x80000000),
        _Filter(0x20, 0, 0, 0),
        _Filter(0x35, 0, 1, 0x40000000),
        _Filter(0x06, 0, 0, 0x00050000 | errno.EPERM),
    ]
    for number in sorted(denied):
        instructions += [_Filter(0x15, 0, 1, number), _Filter(0x06, 0, 0, 0x00050000 | errno.EPERM)]
    instructions.append(_Filter(0x06, 0, 0, 0x7FFF0000))
    array = (_Filter * len(instructions))(*instructions)
    program = _Program(len(instructions), array)
    checked(libc.prctl(22, 2, ctypes.byref(program), 0, 0))  # PR_SET_SECCOMP / FILTER


def confine_memory_only():
    """Strict offline proposer: preloaded Python and pipes only, no new files or sockets.

    Explicit alternative for kernels without Landlock; never selected silently by confine().
    Call after loading dummy source/dependencies and removing credentials from the child environment.
    """
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise GovernanceError("Research sandbox requires Linux x86_64")
    libc = ctypes.CDLL(None, use_errno=True)

    def checked(result):
        if result < 0:
            raise GovernanceError("Memory-only seccomp sandbox unavailable")
        return result

    checked(libc.prctl(38, 1, 0, 0, 0))
    os.closerange(3, 1048576)  # Do not inherit recorder, gateway or audit descriptors.
    _seccomp(libc, checked, memory_only=True)
