# coding:gbk
"""Minimal Big QMT built-in Python lifecycle sanity probe.

Read-only. No account/query/order/cancel calls.
"""

from __future__ import print_function

print("P3_SANITY_TOPLEVEL")


def init(ContextInfo):
    print("P3_SANITY_INIT")


def after_init(ContextInfo):
    print("P3_SANITY_AFTER_INIT")


def handlebar(ContextInfo):
    print("P3_SANITY_HANDLEBAR")


def stop(ContextInfo):
    print("P3_SANITY_STOP")
