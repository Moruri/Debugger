"""Root-cause analysis of timing failures (planned, not implemented).

Future scope: for a given deadline violation, walk the critical path
backward through the trace to identify whether the cause was a slow
upstream SQ, a network transfer, or device contention.
"""
