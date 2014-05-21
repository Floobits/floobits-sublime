#!/usr/local/bin/python
# coding: utf-8
import sys
import warnings
import traceback

try:
    unicode()
except:
    unicode = None


def str_e(e):
    # py3k has __traceback__
    tb = getattr(e, "__traceback__", None)
    if tb is not None:
        return "\n".join(traceback.format_tb(tb))

    # in case of sys.exc_clear()
    _, _, tb = sys.exc_info()
    if tb is not None:
        return "\n".join(traceback.format_tb(tb))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        message = getattr(e, "message", None)
        if message and unicode is not None:
            try:
                return unicode(message, "utf8").encode("utf8")
            except:
                return message.encode("utf8")
        return str(e)

if __name__ == "__main__":
    def test(s):
        try:
            raise Exception(s)
        except Exception as e:
            stre = str_e(e)
            print(type(stre))
            print(stre)

    def test2(s):
        try:
            raise Exception(s)
        except Exception as e:
            sys.exc_clear()
            stre = str_e(e)
            assert str(type(stre)) == "<type 'str'>"
            print(stre)

    tests = ["asdf", u"aß∂ƒ", u"asdf", b"asdf1234"]
    for t in tests:
        test(t)
        if getattr(sys, "exc_clear", None):
            test2(t)
