"""Acceptance-only Python audit guard. Not an engine/alias/Docker wrapper."""
import json
import os
import re
import socket
import sys
import threading
from pathlib import Path

configuration = json.loads(Path(os.environ["DIAVISUALS_TEST_GUARD"]).read_text())
engine = Path(configuration["engine_checkout"]).resolve()
package = Path(configuration["package_root"]).resolve()
consumer = Path(configuration["consumer"]).resolve()
allow_consumer = Path(configuration["allow_consumer"])
log = os.open(configuration["log"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
opening = threading.local()
real_open = os.open


def open_with_observed_dirfd(path, flags, mode=0o777, *, dir_fd=None):
    # CPython's open audit event omits dir_fd. Observe its resolved target while
    # preserving the real openat/no-follow semantics of the provider operation.
    previous = getattr(opening, "path", None)
    opening.path = os.path.join(os.readlink(f"/proc/self/fd/{dir_fd}"), os.fsdecode(path)) if dir_fd is not None and not os.path.isabs(path) else None
    try:
        return real_open(path, flags, mode, dir_fd=dir_fd)
    finally:
        opening.path = previous


os.open = open_with_observed_dirfd


def record(event, value):
    os.write(log, (json.dumps({"event": event, "value": value}) + "\n").encode())


def audit(event, args):
    if event == "socket.connect" and args[0].family in (socket.AF_INET, socket.AF_INET6):
        record("denied-internet", str(args[1]))
        raise PermissionError("offline identity/render proof forbids internet sockets")
    if event == "socket.getaddrinfo":
        record("denied-dns", str(args[0]))
        raise PermissionError("offline proof forbids DNS")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(getattr(opening, "path", None) or os.fsdecode(args[0])).absolute()
        flags = args[2]
        if not flags & os.O_DIRECTORY and not configuration["development"] and path.is_relative_to(engine) and not path.is_relative_to(package) and not path.is_relative_to(Path(sys.prefix)):
            record("denied-checkout", str(path))
            raise PermissionError("installed proof cannot read mutable engine checkout files")
        reading = flags & os.O_ACCMODE != os.O_WRONLY and not flags & os.O_DIRECTORY
        if reading and path.is_relative_to(consumer) and not allow_consumer.exists():
            record("denied-consumer-read", str(path))
            raise PermissionError("live identity must not read consumer content")
    if event in {"os.scandir", "os.listdir"} and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).absolute()
        if path.is_relative_to(consumer) and not allow_consumer.exists():
            record("denied-consumer-list", str(path))
            raise PermissionError("live identity must not enumerate consumer content")
    if event == "subprocess.Popen":
        command = list(args[1]) if not isinstance(args[1], str) else [args[1]]
        record("subprocess", command)
        if Path(command[0]).name in {"uv", "pip", "pip3", "npm", "make"}:
            record("denied-preparation", command)
            raise PermissionError("normal installed launch/work cannot install or prepare dependencies")
        if Path(command[0]).name == "docker":
            if command[1] in {"build", "pull", "load", "tag", "rmi", "system"} or command[1:3] in (["image", "pull"], ["image", "load"], ["image", "tag"], ["image", "rm"]):
                raise PermissionError("normal launch/work must not prepare or mutate images")
            if command[1] == "run" and ("--pull=never" not in command or command[command.index("--network") + 1] != "none"):
                raise PermissionError("renderer must be pull-never and network-none")
            if configuration["strict_rm"] and command[1:3] == ["container", "rm"] and not re.fullmatch(r"[0-9a-f]{64}", command[-1]):
                raise PermissionError("native cleanup must target an exact container ID")


sys.addaudithook(audit)
