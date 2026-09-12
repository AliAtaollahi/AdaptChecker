"""Lexer, AST and recursive-descent parser for the Timed Rebeca fragment.

The fragment is the one in Fig. 1 of the article (Section 2, Preliminaries):

    Model          ::= Class+ Main
    Main           ::= main { RebecInstance* }
    RebecInstance  ::= C r ( r* ) : ( c* ) ;
    Class          ::= reactiveclass C ( n ) { KnownRebecs? Vars? Ctor? MsgSrv* }
    KnownRebecs    ::= knownrebecs { VarDcl }
    Vars           ::= statevars { VarDcl }
    VarDcl         ::= ( T v (, v)* ; )*
    MsgSrv         ::= msgsrv m ( VarDcl ) { Stmt* }
    Stmt           ::= Assign ; | Send ; | if (Expr) MSt [else MSt]
    Assign         ::= v = Expr | v = ?( Expr (, Expr)+ )
    Send           ::= r.m( Expr* ) [after( Expr )]
    MSt            ::= { Stmt* } | Stmt

`delay` and `deadline` are outside the fragment and are rejected with a clear
message rather than silently ignored.

Pure standard library: no third-party dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


class RebecaError(Exception):
    """A lexing or parsing error, carrying file and line."""


# --------------------------------------------------------------------------
# Lexer
# --------------------------------------------------------------------------

KEYWORDS = {
    "reactiveclass", "knownrebecs", "statevars", "msgsrv", "main",
    "if", "else", "after", "self", "true", "false",
    "delay", "deadline",
}

TYPES = {"int", "boolean", "bool", "byte", "short", "long", "double", "float"}

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<line_comment>//[^\n]*)
    | (?P<block_comment>/\*.*?\*/)
    | (?P<number>\d+)
    | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<op><<=|>>=|<=|>=|==|!=|&&|\|\||[-+*/%<>=!(){};:,.?\[\]])
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass(frozen=True)
class Token:
    kind: str          # "ident" | "number" | "op" | "eof"
    text: str
    line: int

    def is_op(self, *texts: str) -> bool:
        return self.kind == "op" and self.text in texts

    def is_ident(self, *texts: str) -> bool:
        return self.kind == "ident" and self.text in texts


def tokenize(source: str, file_name: str = "<input>") -> List[Token]:
    tokens: List[Token] = []
    pos, line = 0, 1
    while pos < len(source):
        m = _TOKEN_RE.match(source, pos)
        if m is None:
            raise RebecaError(
                f"{file_name}:{line}: cannot tokenize {source[pos:pos + 20]!r}")
        text = m.group(0)
        kind = m.lastgroup
        if kind == "ident":
            tokens.append(Token("ident", text, line))
        elif kind == "number":
            tokens.append(Token("number", text, line))
        elif kind == "op":
            tokens.append(Token("op", text, line))
        line += text.count("\n")
        pos = m.end()
    tokens.append(Token("eof", "", line))
    return tokens


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------

class Expr:
    """Base class for expressions.  Every expression can print itself in a
    canonical form (used as node content) and list the variables it reads."""

    def text(self) -> str:                       # pragma: no cover - abstract
        raise NotImplementedError

    def uses(self) -> List[str]:                 # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True)
class Lit(Expr):
    value: str

    def text(self) -> str:
        return self.value

    def uses(self) -> List[str]:
        return []


@dataclass(frozen=True)
class Var(Expr):
    name: str

    def text(self) -> str:
        return self.name

    def uses(self) -> List[str]:
        return [self.name]


@dataclass(frozen=True)
class Unary(Expr):
    op: str
    operand: Expr

    def text(self) -> str:
        return f"{self.op}{self.operand.text()}"

    def uses(self) -> List[str]:
        return list(self.operand.uses())


@dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr

    def text(self) -> str:
        return f"{self.left.text()} {self.op} {self.right.text()}"

    def uses(self) -> List[str]:
        return list(self.left.uses()) + list(self.right.uses())


@dataclass(frozen=True)
class NonDetExpr(Expr):
    """`?(e1, ..., en)` in argument position.  The grammar of Fig. 1 writes
    the nondeterministic choice as a form of assignment; models in the wild
    also pass one straight to a message server, so we accept it there."""
    choices: Tuple[Expr, ...]

    def text(self) -> str:
        return f"?({', '.join(c.text() for c in self.choices)})"

    def uses(self) -> List[str]:
        out: List[str] = []
        for choice in self.choices:
            out.extend(choice.uses())
        return out


@dataclass(frozen=True)
class Paren(Expr):
    inner: Expr

    def text(self) -> str:
        return f"({self.inner.text()})"

    def uses(self) -> List[str]:
        return list(self.inner.uses())


# --------------------------------------------------------------------------
# Statements and declarations
# --------------------------------------------------------------------------

@dataclass
class VarDecl:
    name: str
    type: str
    line: int = 0


class Stmt:
    """Base class for statements."""
    line: int = 0


@dataclass
class Assign(Stmt):
    target: str
    value: Expr
    line: int = 0

    def text(self) -> str:
        return f"{self.target} = {self.value.text()}"


@dataclass
class NonDetAssign(Stmt):
    target: str
    choices: List[Expr] = field(default_factory=list)
    line: int = 0

    def text(self) -> str:
        return f"{self.target} = ?({', '.join(c.text() for c in self.choices)})"


@dataclass
class Send(Stmt):
    receiver: str                  # "self" for an implicit or explicit self-send
    message: str
    args: List[Expr] = field(default_factory=list)
    after: Optional[Expr] = None
    line: int = 0

    def text(self) -> str:
        """Canonical content of a send *statement* node.

        The argument expressions are deliberately left out: the article models
        them as separate actual-in parameter nodes (N_AP), so repeating them
        here would count the same syntax twice.  Receiver, target message
        server and the timing annotation are kept.
        """
        after = self.after.text() if self.after is not None else "0"
        return f"{self.receiver}.{self.message}() after({after})"


@dataclass
class If(Stmt):
    cond: Expr
    then_body: List[Stmt] = field(default_factory=list)
    else_body: List[Stmt] = field(default_factory=list)
    line: int = 0

    def text(self) -> str:
        return f"if ({self.cond.text()})"


@dataclass
class Instantiate(Stmt):
    """An object-instantiation statement of the main block."""
    class_name: str
    rebec_name: str
    known_args: List[str] = field(default_factory=list)
    ctor_args: List[Expr] = field(default_factory=list)
    line: int = 0

    def text(self) -> str:
        known = ", ".join(self.known_args)
        ctor = ", ".join(a.text() for a in self.ctor_args)
        return f"{self.class_name} {self.rebec_name}({known}):({ctor})"


@dataclass
class MsgSrv:
    name: str
    params: List[VarDecl] = field(default_factory=list)
    body: List[Stmt] = field(default_factory=list)
    line: int = 0


@dataclass
class Constructor:
    params: List[VarDecl] = field(default_factory=list)
    body: List[Stmt] = field(default_factory=list)
    line: int = 0


@dataclass
class ReactiveClass:
    name: str
    known_rebecs: List[VarDecl] = field(default_factory=list)
    state_vars: List[VarDecl] = field(default_factory=list)
    constructor: Optional[Constructor] = None
    msgsrvs: List[MsgSrv] = field(default_factory=list)
    line: int = 0

    def msgsrv(self, name: str) -> Optional[MsgSrv]:
        for m in self.msgsrvs:
            if m.name == name:
                return m
        return None


@dataclass
class Model:
    classes: List[ReactiveClass] = field(default_factory=list)
    instances: List[Instantiate] = field(default_factory=list)
    source_name: str = "<input>"

    def klass(self, name: str) -> Optional[ReactiveClass]:
        for c in self.classes:
            if c.name == name:
                return c
        return None

    def class_of_rebec(self, rebec: str) -> Optional[str]:
        for inst in self.instances:
            if inst.rebec_name == rebec:
                return inst.class_name
        return None


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

_BINARY_PRECEDENCE = [
    ("||",),
    ("&&",),
    ("==", "!="),
    ("<", "<=", ">", ">="),
    ("+", "-"),
    ("*", "/", "%"),
]


class Parser:
    def __init__(self, tokens: Sequence[Token], file_name: str = "<input>"):
        self.tokens = list(tokens)
        self.pos = 0
        self.file = file_name

    # -- token helpers ----------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        i = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[i]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def fail(self, message: str) -> "RebecaError":
        return RebecaError(f"{self.file}:{self.cur.line}: {message} "
                           f"(found {self.cur.text!r})")

    def expect_op(self, text: str) -> Token:
        if not self.cur.is_op(text):
            raise self.fail(f"expected {text!r}")
        return self.advance()

    def expect_ident(self) -> Token:
        if self.cur.kind != "ident":
            raise self.fail("expected an identifier")
        return self.advance()

    # -- model ------------------------------------------------------------
    def parse_model(self) -> Model:
        model = Model(source_name=self.file)
        while self.cur.kind != "eof":
            if self.cur.is_ident("reactiveclass"):
                model.classes.append(self.parse_class())
            elif self.cur.is_ident("main"):
                model.instances = self.parse_main()
            else:
                raise self.fail("expected 'reactiveclass' or 'main'")
        if not model.classes:
            raise RebecaError(f"{self.file}: no reactive class found")
        if not model.instances:
            raise RebecaError(f"{self.file}: no 'main' block found")
        return model

    def parse_class(self) -> ReactiveClass:
        line = self.cur.line
        self.advance()                                  # reactiveclass
        name = self.expect_ident().text
        if self.cur.is_op("("):                         # queue length, ignored
            self.advance()
            while not self.cur.is_op(")"):
                self.advance()
            self.expect_op(")")
        self.expect_op("{")
        klass = ReactiveClass(name=name, line=line)
        while not self.cur.is_op("}"):
            if self.cur.is_ident("knownrebecs"):
                self.advance()
                klass.known_rebecs = self.parse_decl_block()
            elif self.cur.is_ident("statevars"):
                self.advance()
                klass.state_vars = self.parse_decl_block()
            elif self.cur.is_ident("msgsrv"):
                klass.msgsrvs.append(self.parse_msgsrv())
            elif self.cur.is_ident(name) and self.peek().is_op("("):
                klass.constructor = self.parse_constructor()
            elif self.cur.kind == "eof":
                raise self.fail(f"unterminated reactive class {name!r}")
            else:
                raise self.fail(f"unexpected token in reactive class {name!r}")
        self.expect_op("}")
        return klass

    def parse_decl_block(self) -> List[VarDecl]:
        self.expect_op("{")
        decls: List[VarDecl] = []
        while not self.cur.is_op("}"):
            decls.extend(self.parse_var_decl())
        self.expect_op("}")
        return decls

    def parse_var_decl(self) -> List[VarDecl]:
        """`T v (, v)* ;` -- one declaration line, possibly several names."""
        line = self.cur.line
        type_name = self.expect_ident().text
        decls = [VarDecl(self.expect_ident().text, type_name, line)]
        while self.cur.is_op(","):
            self.advance()
            decls.append(VarDecl(self.expect_ident().text, type_name, line))
        self.expect_op(";")
        return decls

    def parse_params(self) -> List[VarDecl]:
        self.expect_op("(")
        params: List[VarDecl] = []
        while not self.cur.is_op(")"):
            line = self.cur.line
            type_name = self.expect_ident().text
            params.append(VarDecl(self.expect_ident().text, type_name, line))
            if self.cur.is_op(","):
                self.advance()
        self.expect_op(")")
        return params

    def parse_msgsrv(self) -> MsgSrv:
        line = self.cur.line
        self.advance()                                  # msgsrv
        name = self.expect_ident().text
        params = self.parse_params()
        body = self.parse_block()
        return MsgSrv(name=name, params=params, body=body, line=line)

    def parse_constructor(self) -> Constructor:
        line = self.cur.line
        self.advance()                                  # class name
        params = self.parse_params()
        body = self.parse_block()
        return Constructor(params=params, body=body, line=line)

    def parse_main(self) -> List[Instantiate]:
        self.advance()                                  # main
        self.expect_op("{")
        instances: List[Instantiate] = []
        while not self.cur.is_op("}"):
            instances.append(self.parse_instantiation())
        self.expect_op("}")
        return instances

    def parse_instantiation(self) -> Instantiate:
        line = self.cur.line
        class_name = self.expect_ident().text
        rebec_name = self.expect_ident().text
        self.expect_op("(")
        known: List[str] = []
        while not self.cur.is_op(")"):
            known.append(self.expect_ident().text)
            if self.cur.is_op(","):
                self.advance()
        self.expect_op(")")
        self.expect_op(":")
        self.expect_op("(")
        ctor_args: List[Expr] = []
        while not self.cur.is_op(")"):
            ctor_args.append(self.parse_expr())
            if self.cur.is_op(","):
                self.advance()
        self.expect_op(")")
        self.expect_op(";")
        return Instantiate(class_name, rebec_name, known, ctor_args, line)

    # -- statements -------------------------------------------------------
    def parse_block(self) -> List[Stmt]:
        self.expect_op("{")
        stmts: List[Stmt] = []
        while not self.cur.is_op("}"):
            if self.cur.kind == "eof":
                raise self.fail("unterminated block")
            stmts.append(self.parse_stmt())
        self.expect_op("}")
        return stmts

    def parse_managed_block(self) -> List[Stmt]:
        """MSt ::= { Stmt* } | Stmt"""
        if self.cur.is_op("{"):
            return self.parse_block()
        return [self.parse_stmt()]

    def parse_stmt(self) -> Stmt:
        tok = self.cur
        if tok.is_ident("if"):
            return self.parse_if()
        if tok.is_ident("delay") and self.peek().is_op("("):
            raise RebecaError(
                f"{self.file}:{tok.line}: 'delay' is outside the Timed "
                f"Rebeca fragment this analysis is defined for (Section 2 of "
                f"the article excludes it)")
        if tok.is_op(";"):                              # stray empty statement
            self.advance()
            return self.parse_stmt()
        if tok.kind != "ident":
            raise self.fail("expected a statement")

        # v = ... | recv.m(...) | m(...)
        if self.peek().is_op("="):
            return self.parse_assign()
        if self.peek().is_op(".") or self.peek().is_op("("):
            return self.parse_send()
        raise self.fail("expected an assignment or a send statement")

    def parse_assign(self) -> Stmt:
        line = self.cur.line
        target = self.expect_ident().text
        self.expect_op("=")
        if self.cur.is_op("?"):
            self.advance()
            self.expect_op("(")
            choices = [self.parse_expr()]
            while self.cur.is_op(","):
                self.advance()
                choices.append(self.parse_expr())
            self.expect_op(")")
            self.expect_op(";")
            return NonDetAssign(target, choices, line)
        value = self.parse_expr()
        self.expect_op(";")
        return Assign(target, value, line)

    def parse_send(self) -> Stmt:
        line = self.cur.line
        first = self.expect_ident().text
        if self.cur.is_op("."):
            self.advance()
            receiver, message = first, self.expect_ident().text
        else:
            receiver, message = "self", first           # implicit self-send
        self.expect_op("(")
        args: List[Expr] = []
        while not self.cur.is_op(")"):
            args.append(self.parse_expr())
            if self.cur.is_op(","):
                self.advance()
        self.expect_op(")")
        after: Optional[Expr] = None
        if self.cur.is_ident("after"):
            self.advance()
            self.expect_op("(")
            after = self.parse_expr()
            self.expect_op(")")
        if self.cur.is_ident("deadline"):
            raise RebecaError(
                f"{self.file}:{self.cur.line}: 'deadline' is outside the "
                f"Timed Rebeca fragment this analysis is defined for")
        self.expect_op(";")
        return Send(receiver, message, args, after, line)

    def parse_if(self) -> Stmt:
        line = self.cur.line
        self.advance()                                  # if
        self.expect_op("(")
        cond = self.parse_expr()
        self.expect_op(")")
        then_body = self.parse_managed_block()
        else_body: List[Stmt] = []
        if self.cur.is_ident("else"):
            self.advance()
            if self.cur.is_ident("if"):
                else_body = [self.parse_if()]           # else-if chain
            else:
                else_body = self.parse_managed_block()
        return If(cond, then_body, else_body, line)

    # -- expressions ------------------------------------------------------
    def parse_expr(self, level: int = 0) -> Expr:
        if level >= len(_BINARY_PRECEDENCE):
            return self.parse_unary()
        left = self.parse_expr(level + 1)
        while self.cur.kind == "op" and self.cur.text in _BINARY_PRECEDENCE[level]:
            op = self.advance().text
            right = self.parse_expr(level + 1)
            left = Binary(op, left, right)
        return left

    def parse_unary(self) -> Expr:
        if self.cur.is_op("!") or self.cur.is_op("-"):
            op = self.advance().text
            return Unary(op, self.parse_unary())
        return self.parse_atom()

    def parse_atom(self) -> Expr:
        tok = self.cur
        if tok.is_op("?"):
            self.advance()
            self.expect_op("(")
            choices = [self.parse_expr()]
            while self.cur.is_op(","):
                self.advance()
                choices.append(self.parse_expr())
            self.expect_op(")")
            return NonDetExpr(tuple(choices))
        if tok.is_op("("):
            self.advance()
            inner = self.parse_expr()
            self.expect_op(")")
            return Paren(inner)
        if tok.kind == "number":
            self.advance()
            return Lit(tok.text)
        if tok.kind == "ident":
            self.advance()
            if tok.text in ("true", "false"):
                return Lit(tok.text)
            return Var(tok.text)
        raise self.fail("expected an expression")


def parse_source(source: str, file_name: str = "<input>") -> Model:
    return Parser(tokenize(source, file_name), file_name).parse_model()


def parse_file(path: str) -> Model:
    with open(path, "r", encoding="utf-8") as handle:
        return parse_source(handle.read(), path)
