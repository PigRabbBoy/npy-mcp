"""Notion formula 2.0 interpreter.

Evaluates Notion database formulas client-side from the schema definition
(``formula2.code`` segments). The internal API never returns computed
formula values — the web app evaluates them in JS. This module reimplements
the language per the official function list:

    https://www.notion.com/help/formula-syntax

Design:
    * ``build_expr`` flattens formula2.code into a source string where each
      fpp property reference becomes ``{N}``; refs carry {property, collection}
      metadata used for member access.
    * A recursive-descent parser produces an AST; the evaluator walks it with
      an environment chain (``current``/``index``/``lets`` bindings).
    * Values: None (empty), bool, int/float, str, datetime.date,
      list, Person(dict sentinel), Page(block data + schema).

Anything the interpreter can't parse or evaluate raises _Unsupported and the
caller falls back to its previous behaviour.
"""

from __future__ import annotations

import math
import re
from datetime import date as _date, datetime as _dt, timedelta as _td

BLOCK_MARKER = "\x00block:"


class _Unsupported(Exception):
    pass


Unsupported = _Unsupported  # public alias


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


class Person(dict):
    """Sentinel for a notion_user value ({'uid': ...})."""


class Page:
    """A related page value with access to raw data + target schema."""

    __slots__ = ("data", "schema")

    def __init__(self, data: dict, schema: dict):
        self.data = data or {}
        self.schema = schema or {}

    @property
    def title(self) -> str:
        tprops = (self.data.get("properties") or {}).get("title") or []
        if tprops and isinstance(tprops[0], list):
            return str(tprops[0][0])
        return ""

    def __repr__(self):  # pragma: no cover
        return f"<Page {self.title or self.data.get('id', '?')}>"


def _truthy(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v != ""
    if isinstance(v, (list, tuple)):
        return len(v) > 0
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, bool):
        return v
    if isinstance(v, Page):
        return True
    return bool(v)


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v == ""
    if isinstance(v, (list, tuple)):
        return len(v) == 0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == 0
    return False


def _as_num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        sv = v.strip().replace(",", "")
        if sv == "":
            return None
        try:
            f = float(sv)
            return int(f) if f.is_integer() else f
        except ValueError:
            raise _Unsupported(f"toNumber({v!r})")
    raise _Unsupported("numeric coercion")


def _as_date(v):
    if isinstance(v, _dt):
        return v.date()
    if isinstance(v, _date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                return _dt.strptime(s[:19], fmt).date()
            except ValueError:
                continue
    raise _Unsupported("date coercion")


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, Page):
        return v.title
    if isinstance(v, list):
        return ", ".join(_as_text(x) for x in v)
    return str(v)


def _flat_list(v):
    """Lists stay lists; scalars are wrapped so list ops are uniform."""
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            out.extend(_flat_list(x))
        return out
    return [v]


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
      \s*(?:
        (?P<ref>\{\d+\})
      | (?P<num>\d+\.\d+|\.\d+|\d+)
      | (?P<str>"(?:[^"\\]|\\.)*")
      | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<op>==|!=|>=|<=|&&|\|\||[-+*/%^<>?:().,\[\]])
      )
    """,
    re.VERBOSE,
)


def tokenize(src: str):
    tokens = []
    pos = 0
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if not m or m.end() == pos:
            if src[pos:].strip() == "":
                break
            raise _Unsupported(f"tokenize at {src[pos:pos+20]!r}")
        pos = m.end()
        kind = m.lastgroup
        text = m.group(kind)
        tokens.append((kind, text))
    tokens.append(("eof", ""))
    return tokens


# ---------------------------------------------------------------------------
# Parser → AST tuples
#   ('num', v) ('str', s) ('bool', b) ('ref', n) ('cur',) ('idx',)
#   ('un', op, e) ('bin', op, l, r) ('tern', c, a, b)
#   ('call', name, [args]) ('member', base, refn) ('meth', base, name, args)
#   ('index', base, idxexpr) ('list', [elems])
# ---------------------------------------------------------------------------

_CMP_OPS = {"==", "!=", ">=", "<=", ">", "<"}
_HIGHER_ORDER = {"filter", "map", "some", "every", "find", "findIndex", "sort"}


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, text):
        k, t = self.next()
        if t != text:
            raise _Unsupported(f"expected {text!r} got {t!r}")

    def at(self, text):
        return self.peek()[1] == text

    # precedence climbing
    def parse(self):
        e = self.ternary()
        if self.peek()[0] != "eof":
            raise _Unsupported(f"trailing {self.peek()!r}")
        return e

    def ternary(self):
        cond = self.or_()
        if self.at("?"):
            self.next()
            a = self.ternary()
            self.expect(":")
            b = self.ternary()
            return ("tern", cond, a, b)
        return cond

    def or_(self):
        e = self.and_()
        while self.peek()[1] in ("||", "or") :
            self.next()
            e = ("bin", "or", e, self.and_())
        return e

    def and_(self):
        e = self.not_()
        while self.peek()[1] in ("&&", "and"):
            self.next()
            e = ("bin", "and", e, self.not_())
        return e

    def not_(self):
        if self.peek()[1] in ("not", "!"):
            self.next()
            return ("un", "not", self.not_())
        return self.cmp()

    def cmp(self):
        e = self.add()
        while self.peek()[1] in _CMP_OPS:
            op = self.next()[1]
            e = ("bin", op, e, self.add())
        return e

    def add(self):
        e = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.next()[1]
            e = ("bin", op, e, self.mul())
        return e

    def mul(self):
        e = self.unary()
        while self.peek()[1] in ("*", "/", "%"):
            op = self.next()[1]
            e = ("bin", op, e, self.unary())
        return e

    def unary(self):
        if self.at("-"):
            self.next()
            return ("un", "-", self.unary())
        if self.at("+"):
            self.next()
            return self.unary()
        return self.pow()

    def pow(self):
        e = self.postfix()
        if self.at("^"):
            self.next()
            return ("bin", "^", e, self.unary())
        return e

    def postfix(self):
        e = self.primary()
        while True:
            if self.at("."):
                self.next()
                k, t = self.peek()
                if k == "ref":
                    self.next()
                    e = ("member", e, int(t[1:-1]))
                    continue
                if k == "ident":
                    self.next()
                    name = t
                    args = self.call_args() if self.at("(") else None
                    e = ("meth", e, name, args)
                    continue
                raise _Unsupported(f"postfix .{t!r}")
            if self.at("["):  # literal list handled in primary; here index?
                # Notion formulas don't index with []; treat as unsupported
                raise _Unsupported("[ after expression")
            break
        return e

    def call_args(self):
        self.expect("(")
        args = []
        if not self.at(")"):
            args.append(self.ternary())
            while self.at(","):
                self.next()
                args.append(self.ternary())
        self.expect(")")
        return args

    def primary(self):
        k, t = self.peek()
        if k == "num":
            self.next()
            return ("num", float(t) if "." in t else int(t))
        if k == "str":
            self.next()
            return ("str", t[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        if k == "ref":
            self.next()
            return ("ref", int(t[1:-1]))
        if t == "(":
            self.next()
            e = self.ternary()
            self.expect(")")
            return e
        if t == "[":
            self.next()
            elems = []
            if not self.at("]"):
                elems.append(self.ternary())
                while self.at(","):
                    self.next()
                    elems.append(self.ternary())
            self.expect("]")
            return ("list", elems)
        if t in ("true", "false"):
            self.next()
            return ("bool", t == "true")
        if k == "ident":
            self.next()
            if self.at("("):
                args = self.call_args()
                return ("call", t, args)
            if t == "current":
                return ("cur",)
            if t == "index":
                return ("idx",)
            return ("var", t)
        raise _Unsupported(f"primary {t!r}")


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

_DATE_UNITS = {"years", "quarters", "months", "weeks", "days", "hours", "minutes"}


def _add_units(d: _date, n: float, unit: str) -> _date:
    if unit == "years":
        try:
            base = d.replace(year=d.year + int(n))
        except ValueError:
            base = d.replace(year=d.year + int(n)) - _td(days=1)
        return base + _td(days=round((n - int(n)) * 365.25))
    if unit == "quarters":
        months_f = n * 3
        total = d.month - 1 + int(months_f)
        y = d.year + total // 12
        mo = total % 12 + 1
        import calendar as _cal
        last = _cal.monthrange(y, mo)[1]
        base = d.replace(year=y, month=mo, day=min(d.day, last))
        return base + _td(days=round((months_f - int(months_f)) * 30.44))
    if unit == "months":
        total = d.month - 1 + int(n)
        y = d.year + total // 12
        mo = total % 12 + 1
        import calendar as _cal
        last = _cal.monthrange(y, mo)[1]
        base = d.replace(year=y, month=mo, day=min(d.day, last))
        return base + _td(days=round((n - int(n)) * 30.44))
    if unit == "weeks":
        return d + _td(days=int(round(n * 7)))
    if unit == "days":
        return d + _td(days=int(round(n)))
    if unit in ("seconds", "milliseconds"):
        if unit == "milliseconds":
            n = n / 1000.0
        dt = _dt(d.year, d.month, d.day) + _td(seconds=round(n))
        return dt.date()
    raise _Unsupported(f"dateAdd unit {unit}")


class Interp:
    def __init__(self, ctx):
        # ctx: object with resolve_ref(n) -> value ; member(page_value, n) ;
        #      get_user(uid) ; today()
        self.ctx = ctx
        self.env: dict[str, object] = {}

    # -- env ---------------------------------------------------------------
    def push_env(self, **kw):
        old = self.env
        self.env = {**old, **kw}
        return old

    def pop_env(self, old):
        self.env = old

    # -- entry -------------------------------------------------------------
    def run(self, ast):
        return self.ev(ast)

    def ev(self, node):
        tag = node[0]
        m = getattr(self, f"_e_{tag}")
        return m(node)

    # -- atoms -------------------------------------------------------------
    def _e_num(self, n):
        return n[1]

    def _e_str(self, n):
        return n[1]

    def _e_bool(self, n):
        return n[1]

    def _e_ref(self, n):
        return self.ctx.resolve_ref(n[1])

    def _e_cur(self, n):
        try:
            return self.env["current"]
        except KeyError:
            raise _Unsupported("current outside lambda")

    def _e_idx(self, n):
        try:
            return self.env["index"]
        except KeyError:
            raise _Unsupported("index outside lambda")

    def _e_var(self, n):
        name = n[1]
        if name in self.env:
            return self.env[name]
        raise _Unsupported(f"unknown variable {name}")

    def _e_list(self, n):
        return [self.ev(e) for e in n[1]]

    # -- operators ---------------------------------------------------------
    def _e_un(self, n):
        op, e = n[1], n[2]
        v = self.ev(e)
        if op == "not":
            return not _truthy(v)
        if op == "-":
            n=_as_num(v)
            return None if n is None else -n
        raise _Unsupported(op)

    def _e_bin(self, n):
        op, l, r = n[1], n[2], n[3]
        if op in ("and", "or"):
            lv = _truthy(self.ev(l))
            if op == "and":
                return (self.ev(r) if lv else False) if lv else False
            return True if lv else _truthy(self.ev(r))
        lv = self.ev(l)
        rv = self.ev(r)
        if op in _CMP_OPS or op == "==":
            return self._cmp(op, lv, rv)
        if lv is None or rv is None:
            return None
        if op == "+":
            if isinstance(lv, str) or isinstance(rv, str):
                return _as_text(lv) + _as_text(rv)
            if isinstance(lv, _date) or isinstance(rv, _date):
                raise _Unsupported("date +")
            if isinstance(lv, list) and isinstance(rv, list):
                return _flat_list(lv + rv)
            a,b=_as_num(lv),_as_num(rv)
            if a is None or b is None:
                return None
            return a + b
        if op == "-":
            if isinstance(lv, _date) and isinstance(rv, _date):
                return (lv - rv).days
            a,b=_as_num(lv),_as_num(rv)
            if a is None or b is None:
                return None
            return a - b
        if op == "*":
            a,b=_as_num(lv),_as_num(rv)
            if a is None or b is None:
                return None
            return a * b
        if op == "/":
            d = _as_num(rv)
            if not d:
                return None
            return _as_num(lv) / d
        if op == "%":
            a,b=_as_num(lv),_as_num(rv)
            if a is None or b is None:
                return None
            return a % b
        if op == "^":
            a,b=_as_num(lv),_as_num(rv)
            if a is None or b is None:
                return None
            return a ** b
        raise _Unsupported(op)

    def _cmp(self, op, lv, rv):
        # normalize page/person/text comparisons
        if isinstance(lv, Page):
            lv = lv.title
        if isinstance(rv, Page):
            rv = rv.title
        if lv is None or rv is None:
            if op == "==":
                return lv is None and rv is None
            if op == "!=":
                return not (lv is None and rv is None)
            return False
        if isinstance(lv, list) and rv is not None and not isinstance(rv, list):
            return any(self._cmp(op, x, rv) for x in lv)
        if isinstance(rv, list) and lv is not None and not isinstance(lv, list):
            return any(self._cmp(op, lv, x) for x in rv)
        both_num = isinstance(lv, (int, float)) and isinstance(rv, (int, float))
        if op == "==":
            if both_num or (isinstance(lv, (int, float)) and isinstance(rv, str)):
                try:
                    return _as_num(lv) == _as_num(rv)
                except _Unsupported:
                    return False
            return _as_text(lv) == _as_text(rv)
        if op == "!=":
            return not self._cmp("==", lv, rv)
        try:
            if both_num:
                a, b = lv, rv
            else:
                a, b = _as_text(lv), _as_text(rv)
                if op in (">", ">=", "<", "<="):
                    da, db = _maybe_date(a), _maybe_date(b)
                    if da and db:
                        a, b = da, db
            if op == ">":
                return a > b
            if op == ">=":
                return a >= b
            if op == "<":
                return a < b
            if op == "<=":
                return a <= b
        except TypeError:
            raise _Unsupported(f"compare {lv!r} {op} {rv!r}")
        raise _Unsupported(op)

    def _e_tern(self, n):
        return self.ev(n[2]) if _truthy(self.ev(n[1])) else self.ev(n[3])

    # -- member / method ---------------------------------------------------
    def _e_member(self, n):
        base = self.ev(n[1])
        return self.ctx.member(base, n[2])

    def _e_meth(self, n):
        _, base_ast, name, args_ast = n
        if base_ast is None:
            return self._global_call(name, args_ast or [])
        base = self.ev(base_ast)
        argvals = [None] * len(args_ast or [])
        lazy = name in _HIGHER_ORDER
        vals = None if lazy else [self.ev(a) for a in (args_ast or [])]
        return self._method(name, base, args_ast or [], vals)

    def _e_call(self, n):
        return self._global_call(n[1], n[2])

    def _e_index(self, n):  # pragma: no cover
        raise _Unsupported("index")

    # -- lambdas -----------------------------------------------------------
    def _lambda_eval(self, ast, item, idx):
        old = self.push_env(current=item, index=idx)
        try:
            return self.ev(ast)
        finally:
            self.pop_env(old)

    # -- dispatch ----------------------------------------------------------
    def _method(self, name, base, arg_asts, vals):
        ctx = self.ctx

        # ---- list methods (base may be scalar→wrapped) --------------------
        lst = base if isinstance(base, list) else None

        def items():
            return _flat_list(base)

        def one_arg(i=0):
            return vals[i] if vals and len(vals) > i else self.ev(arg_asts[i])

        if name == "length":
            if isinstance(base, str):
                return len(base)
            return len(items())
        if name == "at":
            i = int(_as_num(one_arg()))
            seq = base if isinstance(base, list) else items()
            try:
                return seq[i]
            except IndexError:
                return None
        if name == "first":
            seq = items()
            return seq[0] if seq else None
        if name == "last":
            seq = items()
            return seq[-1] if seq else None
        if name == "slice":
            a = int(_as_num(vals[0]))
            b = int(_as_num(vals[1])) if len(vals) > 1 else None
            seq = base if isinstance(base, str) else items()
            return seq[a:b]
        if name == "concat":
            other = one_arg(0) if arg_asts else []
            return _flat_list((base if isinstance(base, list) else items())) + _flat_list(other)
        if name == "sort":
            seq = items()
            if arg_asts:  # sort by key expr
                keyed = [(self._lambda_eval(arg_asts[0], it, i), i, it) for i, it in enumerate(seq)]
                keyed.sort(key=lambda t: _sort_key(t[0]))
                return [it for _, _, it in keyed]
            return sorted(seq, key=_sort_key)
        if name == "reverse":
            seq = items()
            return list(reversed(seq))
        if name == "join":
            sep = _as_text(one_arg()) if arg_asts else ","
            return sep.join(_as_text(x) for x in items())
        if name == "split":
            seq = _as_text(base).split(_as_text(one_arg()))
            return seq
        if name == "unique":
            seen, out = set(), []
            for x in items():
                kx = _as_text(x)
                if kx not in seen:
                    seen.add(kx)
                    out.append(x)
            return out
        if name == "includes":
            w = one_arg()
            return any(self.ctx.eq(x, w) for x in items())
        if name == "flat":
            return _flat_list(base)
        if name == "filter":
            out = []
            for i, it in enumerate(items()):
                if _truthy(self._lambda_eval(arg_asts[0], it, i)):
                    out.append(it)
            return out
        if name == "map":
            return [self._lambda_eval(arg_asts[0], it, i) for i, it in enumerate(items())]
        if name == "some":
            return any(_truthy(self._lambda_eval(arg_asts[0], it, i)) for i, it in enumerate(items()))
        if name == "every":
            return all(_truthy(self._lambda_eval(arg_asts[0], it, i)) for i, it in enumerate(items()))
        if name == "find":
            for i, it in enumerate(items()):
                if _truthy(self._lambda_eval(arg_asts[0], it, i)):
                    return it
            return None
        if name == "findIndex":
            for i, it in enumerate(items()):
                if _truthy(self._lambda_eval(arg_asts[0], it, i)):
                    return i
            return -1

        # ---- person methods ----------------------------------------------
        if name in ("name", "email"):
            targets = items()
            outs = [ctx.person_field(p, name) for p in targets]
            return outs[0] if len(outs) == 1 else outs

        # ---- date methods on date value ----------------------------------
        if name == "dateAdd":
            if not base or not one_arg():
                return None
            return _add_units(_as_date(base), _as_num(one_arg()), _as_text(one_arg(1)))
        if name == "dateSubtract":
            if not base or not one_arg():
                return None
            neg = -_as_num(one_arg())
            return _add_units(_as_date(base), neg, _as_text(one_arg(1)))
        if name == "formatDate":
            return _fmt_date(_as_date(base), _as_text(one_arg()))
        if name in ("year", "month", "day", "date", "week", "hour", "minute"):
            d = _as_date(base)
            return {
                "year": d.year,
                "month": d.month,
                "day": d.isoweekday(),
                "date": d.day,
                "week": _iso_week(d),
            }[name]
        if name == "timestamp":
            d = _as_date(base)
            dt = _dt(d.year, d.month, d.day)
            return int((dt - _dt(1970, 1, 1)).total_seconds() * 1000)
        if name == "dateStart":
            return base
        if name == "dateEnd":
            return base
        if name == "style" or name == "unstyle":
            return _as_text(base)  # display-only: strip styling
        if name == "trim":
            return _as_text(base).strip()
        if name == "lower":
            return _as_text(base).lower()
        if name == "upper":
            return _as_text(base).upper()
        if name == "repeat":
            return _as_text(base) * int(_as_num(one_arg()))
        if name == "contains":
            return _as_text(one_arg()) in _as_text(base)
        if name == "test":
            return re.search(_as_text(one_arg()), _as_text(base)) is not None
        if name == "match":
            return re.findall(_as_text(one_arg()), _as_text(base))
        if name == "replace":
            pat, rep = _as_text(one_arg(0)), _as_text(one_arg(1))
            return re.sub(pat, rep, _as_text(base), count=1)
        if name == "replaceAll":
            pat, rep = _as_text(one_arg(0)), _as_text(one_arg(1))
            return re.sub(pat, rep, _as_text(base))
        if name == "substring":
            s = _as_text(base)
            a = int(_as_num(vals[0]))
            b = int(_as_num(vals[1])) if len(vals) > 1 else None
            return s[a:b]
        if name == "link":
            label = _as_text(base)
            url = _as_text(one_arg())
            return f"[{label}]({url})"
        if name == "format":
            return _as_text(base)
        for ho in _HIGHER_ORDER:
            if name == ho:
                seq = _flat_list(ev_i(0))
                lam = arg_asts[1]
                if ho == "filter":
                    return [it for i, it in enumerate(seq) if _truthy(self._lambda_eval(lam, it, i))]
                if ho == "map":
                    return [self._lambda_eval(lam, it, i) for i, it in enumerate(seq)]
                if ho == "some":
                    return any(_truthy(self._lambda_eval(lam, it, i)) for i, it in enumerate(seq))
                if ho == "every":
                    return all(_truthy(self._lambda_eval(lam, it, i)) for i, it in enumerate(seq))
                if ho == "find":
                    for i, it in enumerate(seq):
                        if _truthy(self._lambda_eval(lam, it, i)):
                            return it
                    return None
                if ho == "findIndex":
                    for i, it in enumerate(seq):
                        if _truthy(self._lambda_eval(lam, it, i)):
                            return i
                    return -1
        if name in ("padStart", "padEnd"):
            txt = _as_text(base)
            target = int(_as_num(one_arg()) or 0)
            pad = _as_text(one_arg(1)) if arg_asts and len(arg_asts) > 1 else " "
            if not pad:
                return txt
            fill = (pad * max(0, target))[:max(0, target - len(txt))]
            return (fill + txt) if name == "padStart" else (txt + fill)
        if name == "splice":
            start = int(_as_num(one_arg()) or 0)
            delc = int(_as_num(one_arg(1))) if len(arg_asts) > 1 else 0
            ins = [self.ev(a) for a in arg_asts[2:]] if arg_asts else []
            if isinstance(base, str):
                return base[:start] + "".join(_as_text(x) for x in ins) + base[start + delc:]
            lst = items()
            return lst[:start] + ins + lst[start + delc:]
        if name == "id":
            if isinstance(base, Page):
                return base.data.get("id", "")
            raise _Unsupported("id() on non-page")

        raise _Unsupported(f".{name}()")

    def _global_call(self, name, arg_asts):
        ctx = self.ctx

        def ev_i(i):
            return self.ev(arg_asts[i])

        def nums():
            out = []
            for a in arg_asts:
                v = self.ev(a)
                if isinstance(v, list):
                    out.extend(_as_num(x) for x in v)
                else:
                    out.append(_as_num(v))
            return out

        if name == "if":
            return self.ev(arg_asts[1]) if _truthy(ev_i(0)) else self.ev(arg_asts[2])
        if name == "ifs":
            i = 0
            while i + 1 < len(arg_asts):
                if _truthy(ev_i(i)):
                    return self.ev(arg_asts[i + 1])
                i += 2
            return self.ev(arg_asts[-1]) if len(arg_asts) % 2 == 1 else None
        if name == "let":
            vn = _var_name(arg_asts[0])
            old = self.push_env(**{vn: self.ev(arg_asts[1])})
            try:
                return self.ev(arg_asts[2])
            finally:
                self.pop_env(old)
        if name == "lets":
            pairs = (len(arg_asts) - 1) // 2
            binds = {}
            for k in range(pairs):
                binds[_var_name(arg_asts[k * 2])] = self.ev(arg_asts[k * 2 + 1])
            old = self.push_env(**binds)
            try:
                return self.ev(arg_asts[-1])
            finally:
                self.pop_env(old)
        if name == "empty":
            return _is_empty(ev_i(0))
        if name == "not":
            return not _truthy(ev_i(0))
        if name == "and":
            return all(_truthy(ev_i(i)) for i in range(len(arg_asts)))
        if name == "or":
            return any(_truthy(ev_i(i)) for i in range(len(arg_asts)))
        if name in ("add", "sum"):
            xs = [x for x in nums() if x is not None]
            return sum(xs) if xs else None
        if name == "subtract":
            if nums()[0] is None or nums()[1] is None:
                return None
            return nums()[0] - nums()[1]
        if name == "multiply":
            p = 1
            xs = nums()
            if any(x is None for x in xs):
                return None
            for x in xs:
                p *= x
            return p
        if name == "divide":
            a, b = nums()[0], nums()[1]
            if not b:
                return None
            return a / b
        if name == "mod":
            if nums()[0] is None or nums()[1] is None:
                return None
            return nums()[0] % nums()[1]
        if name == "pow":
            if nums()[0] is None or nums()[1] is None:
                return None
            return nums()[0] ** nums()[1]
        if name == "min":
            xs=[x for x in nums() if x is not None]
            return min(xs) if xs else None
        if name == "max":
            xs=[x for x in nums() if x is not None]
            return max(xs) if xs else None
        if name == "median":
            xs = sorted(nums())
            n = len(xs)
            if n == 0:
                return None
            mid = n // 2
            return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2
        if name == "mean":
            xs = nums()
            return sum(xs) / len(xs) if xs else None
        def _un(f):
            x = nums()[0]
            return None if x is None else f(x)
        if name == "abs":
            return _un(abs)
        if name == "round":
            xs = nums()
            if xs[0] is None:
                return None
            nd = int(xs[1]) if len(xs) > 1 else 0
            r = round(xs[0], nd)
            return int(r) if nd <= 0 else r
        if name == "ceil":
            return _un(lambda x: int(math.ceil(x)))
        if name == "floor":
            return _un(lambda x: int(math.floor(x)))
        if name == "sqrt":
            return _un(math.sqrt)
        if name == "cbrt":
            return _un(lambda v: math.copysign(abs(v) ** (1 / 3), v))
        if name == "exp":
            return _un(math.exp)
        if name == "ln":
            return _un(math.log)
        if name == "log10":
            return _un(math.log10)
        if name == "log2":
            return _un(math.log2)
        if name == "sign":
            return _un(lambda v: (v > 0) - (v < 0))
        if name == "pi":
            return math.pi
        if name == "e":
            return math.e
        if name == "toNumber":
            try:
                return _as_num(ev_i(0))
            except _Unsupported:
                return None
        if name == "now":
            return ctx.now(with_time=True)
        if name == "today":
            return ctx.today()
        if name == "dateBetween":
            if not ev_i(0) or not ev_i(1):
                return None
            a = _as_date(ev_i(0))
            b = _as_date(ev_i(1))
            unit = _as_text(ev_i(2))
            secs = (_dt(a.year, a.month, a.day) - _dt(b.year, b.month, b.day)).total_seconds()
            days = math.floor(secs / 86400)
            if unit == "days":
                return days
            if unit == "weeks":
                return days // 7
            if unit == "months":
                return round(days / 30.44)
            if unit == "years":
                return round(days / 365.25)
            if unit == "hours":
                return days * 24
            if unit == "minutes":
                return days * 1440
            if unit == "quarters":
                return round(days / 91.31)
            if unit == "seconds":
                return int(secs)
            if unit == "milliseconds":
                return int(secs * 1000)
            raise _Unsupported(unit)
        if name == "dateAdd":
            if not ev_i(0) or not ev_i(1):
                return None
            return _add_units(_as_date(ev_i(0)), _as_num(ev_i(1)), _as_text(ev_i(2)))
        if name == "dateSubtract":
            if not ev_i(0) or not ev_i(1):
                return None
            return _add_units(_as_date(ev_i(0)), -_as_num(ev_i(1)), _as_text(ev_i(2)))
        if name in ("year", "month", "day", "date", "week", "hour", "minute"):
            d = _as_date(ev_i(0))
            return {
                "year": d.year,
                "month": d.month,
                "day": d.isoweekday(),
                "date": d.day,
                "week": _iso_week(d),
            }[name]
        if name == "parseDate":
            s = _as_text(ev_i(0))
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    return _dt.strptime(s[:16].replace("Z", ""), fmt).date()
                except ValueError:
                    continue
            return None
        if name == "formatDate":
            return _fmt_date(_as_date(ev_i(0)), _as_text(ev_i(1)))
        if name == "formatNumber":
            v = _as_num(ev_i(0))
            style = _as_text(ev_i(1)) if len(arg_asts) > 1 else ""
            precision = int(_as_num(ev_i(2))) if len(arg_asts) > 2 else 2
            if style == "usd":
                return f"${v:,.{precision}f}"
            return f"{v:,.{precision}f}"
        if name == "format":
            return _as_text(ev_i(0))
        if name == "style":
            return _as_text(ev_i(0))
        if name == "unstyle":
            return _as_text(ev_i(0))
        if name == "link":
            return f"[{_as_text(ev_i(0))}]({_as_text(ev_i(1))})"
        if name == "length":
            v = ev_i(0)
            if isinstance(v, str):
                return len(v)
            return len(_flat_list(v))
        if name == "substring":
            s = _as_text(ev_i(0))
            a = int(_as_num(ev_i(1)))
            b = int(_as_num(ev_i(2))) if len(arg_asts) > 2 else None
            return s[a:b]
        if name == "contains":
            return _as_text(ev_i(1)) in _as_text(ev_i(0))
        if name == "test":
            return re.search(_as_text(ev_i(1)), _as_text(ev_i(0))) is not None
        if name == "match":
            return re.findall(_as_text(ev_i(1)), _as_text(ev_i(0)))
        if name == "replace":
            return re.sub(_as_text(ev_i(1)), _as_text(ev_i(2)), _as_text(ev_i(0)), count=1)
        if name == "replaceAll":
            return re.sub(_as_text(ev_i(1)), _as_text(ev_i(2)), _as_text(ev_i(0)))
        if name == "lower":
            return _as_text(ev_i(0)).lower()
        if name == "upper":
            return _as_text(ev_i(0)).upper()
        if name == "repeat":
            return _as_text(ev_i(0)) * int(_as_num(ev_i(1)))
        if name == "concat":
            out = []
            for a in arg_asts:
                out.extend(_flat_list(ev_i(0) if False else self.ev(a)))
            return out
        if name == "at":
            seq = _flat_list(ev_i(0))
            i = int(_as_num(ev_i(1)))
            try:
                return seq[i]
            except IndexError:
                return None
        if name == "first":
            seq = _flat_list(ev_i(0))
            return seq[0] if seq else None
        if name == "last":
            seq = _flat_list(ev_i(0))
            return seq[-1] if seq else None
        if name == "slice":
            v = ev_i(0)
            a = int(_as_num(ev_i(1)))
            b = int(_as_num(ev_i(2))) if len(arg_asts) > 2 else None
            return v[a:b] if isinstance(v, str) else _flat_list(v)[a:b]
        if name == "join":
            seq = _flat_list(ev_i(0))
            sep = _as_text(ev_i(1)) if len(arg_asts) > 1 else ","
            return sep.join(_as_text(x) for x in seq)
        if name == "split":
            return _as_text(ev_i(0)).split(_as_text(ev_i(1)))
        if name == "sort":
            seq = _flat_list(ev_i(0))
            return sorted(seq, key=_sort_key)
        if name == "reverse":
            return list(reversed(_flat_list(ev_i(0))))
        if name == "unique":
            seen, out = set(), []
            for x in _flat_list(ev_i(0)):
                k = _as_text(x)
                if k not in seen:
                    seen.add(k)
                    out.append(x)
            return out
        if name == "includes":
            w = ev_i(1)
            return any(ctx.eq(x, w) for x in _flat_list(ev_i(0)))
        if name == "flat":
            return _flat_list(ev_i(0))
        for ho in _HIGHER_ORDER:
            if name == ho:
                seq = _flat_list(ev_i(0))
                lam = arg_asts[1]
                if ho == "filter":
                    return [it for i, it in enumerate(seq) if _truthy(self._lambda_eval(lam, it, i))]
                if ho == "map":
                    return [self._lambda_eval(lam, it, i) for i, it in enumerate(seq)]
                if ho == "some":
                    return any(_truthy(self._lambda_eval(lam, it, i)) for i, it in enumerate(seq))
                if ho == "every":
                    return all(_truthy(self._lambda_eval(lam, it, i)) for i, it in enumerate(seq))
                if ho == "find":
                    for i, it in enumerate(seq):
                        if _truthy(self._lambda_eval(lam, it, i)):
                            return it
                    return None
                if ho == "findIndex":
                    for i, it in enumerate(seq):
                        if _truthy(self._lambda_eval(lam, it, i)):
                            return i
                    return -1
        if name in ("padStart", "padEnd"):
            txt = _as_text(ev_i(0))
            target = int(_as_num(ev_i(1)) or 0)
            pad = _as_text(ev_i(2)) if len(arg_asts) > 2 else " "
            if not pad:
                return txt
            fill = (pad * max(0, target))[:max(0, target - len(txt))]
            return (fill + txt) if name == "padStart" else (txt + fill)
        if name == "splice":
            seq = ev_i(0)
            start = int(_as_num(ev_i(1)) or 0)
            delc = int(_as_num(ev_i(2))) if len(arg_asts) > 2 else 0
            inserts = [self.ev(a) for a in arg_asts[3:]]
            if isinstance(seq, str):
                out = seq[:start] + "".join(_as_text(x) for x in inserts) + seq[start + delc:]
                return out
            lst = _flat_list(seq)
            newl = lst[:start] + inserts + lst[start + delc:]
            return newl
        if name == "id":
            if arg_asts:
                v = ev_i(0)
                if isinstance(v, Page):
                    return v.data.get("id", "")
            return ctx.self_id()
        if name == "name" or name == "email":
            v = ev_i(0)
            return ctx.person_field(v, name)
        if name == "timestamp":
            d = _as_date(ev_i(0))
            return int((_dt(d.year, d.month, d.day) - _dt(1970, 1, 1)).total_seconds() * 1000)
        if name == "fromTimestamp":
            ms = int(_as_num(ev_i(0)))
            return _dt.utcfromtimestamp(ms / 1000).date()

        raise _Unsupported(f"{name}()")


def _var_name(ast):
    if ast[0] == "var":
        return ast[1]
    if ast[0] == "str":
        return ast[1]
    raise _Unsupported("variable name")


def _maybe_date(s):
    try:
        return _as_date(s)
    except _Unsupported:
        return None


def _sort_key(v):
    if isinstance(v, bool):
        return (2, v)
    if isinstance(v, (int, float)):
        return (0, v)
    if isinstance(v, _date):
        return (1, v.toordinal())
    if isinstance(v, Page):
        return (3, v.title)
    return (3, _as_text(v))


def _iso_week(d: _date) -> int:
    return d.isocalendar()[1]


_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


def _fmt_date(d: _date, fmt: str) -> str:
    out = fmt
    out = out.replace("MMMM", f"{d:%B}")
    out = out.replace("MM", f"{d.month:02d}")
    out = out.replace("YYYY", str(d.year))
    out = out.replace("DD", f"{d.day:02d}")
    out = out.replace("Y", str(d.year))
    out = out.replace("D", str(d.day))
    out = out.replace("M", f"{d.month:02d}")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_expr(prop_schema: dict):
    """Flatten formula2.code into (src, refs) with {N} placeholders."""
    refs: list[dict] = []
    parts: list[str] = []
    code = (prop_schema.get("formula2") or {}).get("code") or []
    for seg in code:
        if isinstance(seg, list) and seg:
            if seg[0] == "‣" and len(seg) > 1 and seg[1]:
                try:
                    meta = seg[1][0][1]
                    parts.append("{" + str(len(refs)) + "}")
                    refs.append(meta)
                    continue
                except Exception:
                    pass
            parts.append(str(seg[0]))
        elif isinstance(seg, str):
            parts.append(seg)
    return "".join(parts), refs


def evaluate(prop_schema: dict, ctx):
    """Parse+eval formula. Raises _Unsupported when shape/language unknown.

    ctx must provide: resolve_ref(n), member(value, n), eq(a,b),
    person_field(person, which), now(), today(), self_id().
    """
    src, refs = build_expr(prop_schema)
    if not src.strip():
        raise _Unsupported("empty")
    parser = Parser(tokenize(src))
    ast = parser.parse()
    interp = Interp(ctx)
    return interp.run(ast)


def encode_expr(src: str, prop_meta: dict[str, dict] | None = None) -> list:
    """Encode a formula source string into Notion formula2.code segments.

    Inverse of build_expr: literals become single-element segments; property
    references written as {"Prop Name"} become '‣' fpp segments.

    prop_meta maps a display property name to {"property": <pid>,
    "collection": {"id":..., "table":"collection", "spaceId":...}} — the same
    shape the web client emits. Without a matching entry the fpp carries the
    name only (the client-side evaluator resolves names, but the Notion UI
    needs the id, so callers building schemas SHOULD provide meta).
    """
    prop_meta = prop_meta or {}
    code: list = []
    idx = 0
    for m in re.finditer(r'\{"([^"]+)"\}', src):
        literal = src[idx:m.start()]
        if literal:
            code.append([literal])
        display = m.group(1)
        meta = {"name": display, "verbose": False}
        extra = prop_meta.get(display)
        if extra:
            meta.update(extra)
        code.append(["‣", [["fpp", meta]]])
        idx = m.end()
    tail = src[idx:]
    if tail:
        code.append([tail])
    return code
