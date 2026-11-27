"""Loaded in test Python subprocesses to make accidental network access fail."""
import socket

def _blocked(*args, **kwargs):
    raise AssertionError("Network access is forbidden in offline tests.")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
