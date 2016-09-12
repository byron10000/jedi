from textwrap import dedent

import pytest

import jedi
from jedi._compatibility import u
from jedi.common import splitlines
from jedi import cache
from jedi.parser import load_grammar
from jedi.parser.fast import FastParser, DiffParser
from jedi.parser import ParserWithRecovery
from jedi.parser.utils import save_parser


def test_add_to_end():
    """
    fast_parser doesn't parse everything again. It just updates with the
    help of caches, this is an example that didn't work.
    """

    a = dedent("""\
    class Abc():
        def abc(self):
            self.x = 3

    class Two(Abc):
        def g(self):
            self
    """)      # ^ here is the first completion

    b = "    def h(self):\n" \
        "        self."
    assert jedi.Script(a, 7, 12, 'example.py').completions()
    assert jedi.Script(a + b, path='example.py').completions()

    a = a[:-1] + '.\n'
    assert jedi.Script(a, 7, 13, 'example.py').completions()
    assert jedi.Script(a + b, path='example.py').completions()


def _check_error_leafs(node):
    try:
        children = node.children
    except AttributeError:
        if node.type == 'error_leaf':
            return True
    else:
        for child in children:
            if _check_error_leafs(child):
                return True
    return False


class Differ(object):
    def __init__(self):
        self._first_use = True

    def initialize(self, source):
        grammar = load_grammar()
        self.parser = ParserWithRecovery(grammar, source)
        return self.parser.module

    def parse(self, source, copies=0, parsers=0, allow_error_leafs=False):
        lines = splitlines(source, keepends=True)
        diff_parser = DiffParser(self.parser)
        new_module = diff_parser.update(lines)
        assert source == new_module.get_code()
        assert diff_parser._copy_count == copies
        assert diff_parser._parser_count == parsers
        self.parser.module = new_module
        self.parser._parsed = new_module
        if not allow_error_leafs:
            assert not _check_error_leafs(new_module)
        return new_module


@pytest.fixture()
def differ():
    return Differ()


def test_change_and_undo(differ):
    # Empty the parser cache for the path None.
    cache.parser_cache.pop(None, None)
    func_before = 'def func():\n    pass\n'
    # Parse the function and a.
    differ.initialize(func_before + 'a')
    # Parse just b.
    differ.parse(func_before + 'b', copies=1, parsers=1)
    # b has changed to a again, so parse that.
    differ.parse(func_before + 'a', copies=1, parsers=1)
    # Same as before no parsers should be used.
    differ.parse(func_before + 'a', copies=1)

    # Getting rid of an old parser: Still no parsers used.
    differ.parse('a', copies=1)
    # Now the file has completely changed and we need to parse.
    differ.parse('b', parsers=1)
    # And again.
    differ.parse('a', parsers=1)


def test_positions(differ):
    # Empty the parser cache for the path None.
    cache.parser_cache.pop(None, None)

    func_before = 'class A:\n pass\n'
    m = differ.initialize(func_before + 'a')
    assert m.start_pos == (1, 0)
    assert m.end_pos == (3, 1)

    m = differ.parse('a', copies=1)
    assert m.start_pos == (1, 0)
    assert m.end_pos == (1, 1)

    m = differ.parse('a\n\n', parsers=1)
    assert m.end_pos == (3, 0)
    m = differ.parse('a\n\n ', copies=1, parsers=1)
    assert m.end_pos == (3, 1)
    m = differ.parse('a ', parsers=1)
    assert m.end_pos == (1, 2)


def test_if_simple(differ):
    src = dedent('''\
    if 1:
        a = 3
    ''')
    else_ = "else:\n    a = ''\n"

    differ.initialize(src + 'a')
    differ.parse(src + else_ + "a", copies=0, parsers=1)

    differ.parse(else_, parsers=1, allow_error_leafs=True)
    differ.parse(src + else_, parsers=1)


def test_func_with_for_and_comment(differ):
    # The first newline is important, leave it. It should not trigger another
    # parser split.
    src = dedent("""\

    def func():
        pass


    for a in [1]:
        # COMMENT
        a""")
    differ.initialize(src)
    differ.parse('a\n' + src, copies=1, parsers=1)


def test_one_statement_func(differ):
    src = dedent("""\
    first
    def func(): a
    """)
    differ.initialize(src + 'second')
    differ.parse(src + 'def second():\n a', parsers=1, copies=1)


def test_for_on_one_line(differ):
    src = dedent("""\
    foo = 1
    for x in foo: pass

    def hi():
        pass
    """)
    differ.initialize(src)

    src = dedent("""\
    def hi():
        for x in foo: pass
        pass

    pass
    """)
    differ.parse(src, parsers=2)

    src = dedent("""\
    def hi():
        for x in foo: pass

        def nested():
            pass
    """)
    differ.parse(src, parsers=1, copies=1)


def test_open_parentheses(differ):
    func = 'def func():\n a'
    code = u('isinstance(\n\n' + func)
    differ.initialize(code)

    differ.parse('isinstance(\n' + func, copies=1, parsers=1)


def test_backslash(differ):
    src = dedent(r"""
    a = 1\
        if 1 else 2
    def x():
        pass
    """)
    differ.initialize(src)

    src = dedent(r"""
    def x():
        a = 1\
    if 1 else 2
        def y():
            pass
    """)
    differ.parse(src, parsers=2)

    src = dedent(r"""
    def first():
        if foo \
                and bar \
                or baz:
            pass
    def second():
        pass
    """)
    differ.parse(src, parsers=2)
