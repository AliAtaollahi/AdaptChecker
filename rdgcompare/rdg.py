"""The Rebeca Dependence Graph (RDG) of Section 3 of the article.

    RDG(M) = (N, E)
    N = N_S u N_C u N_E u N_FP u N_AP u N_SV
    E = E_C u E_D u E_I u E_M u E_B u E_A

Node kinds
    N_C   class-object node, one per reactive class
    N_E   entry node: the main block, each constructor, each message server
    N_FP  formal-in parameter node -- the assignment `v = v_in` that copies a
          value out of the message into the formal parameter
    N_AP  actual-in parameter node -- the assignment `v_in = expr` that copies
          an actual parameter into the message
    N_SV  state-variable node, one per state variable declaration
    N_S   statement node: assignments, nondeterministic assignments,
          conditionals, sends, and object instantiations in main

Edge kinds
    E_C   control dependence
    E_D   data dependence (Section 2, Program Dependence Graph)
    E_I   intra-rebec dependence
    E_M   member dependence
    E_B   binding dependence
    E_A   activation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .rebeca import (
    Assign, Constructor, Expr, If, Instantiate, Model, MsgSrv, NonDetAssign,
    ReactiveClass, Send, Stmt, VarDecl,
)


class NodeKind(str, Enum):
    C = "N_C"
    E = "N_E"
    S = "N_S"
    FP = "N_FP"
    AP = "N_AP"
    SV = "N_SV"


class EdgeKind(str, Enum):
    C = "E_C"      # control
    D = "E_D"      # data
    I = "E_I"      # intra-rebec
    M = "E_M"      # member
    B = "E_B"      # binding
    A = "E_A"      # activation


EDGE_TITLE = {
    EdgeKind.C: "control",
    EdgeKind.D: "data",
    EdgeKind.I: "intra-rebec",
    EdgeKind.M: "member",
    EdgeKind.B: "binding",
    EdgeKind.A: "activation",
}


@dataclass
class Node:
    id: str
    kind: NodeKind
    content: Tuple                 # what Def. "RDG Equivalence" compares
    label: str                     # what the .dot shows
    owner: Optional[str] = None    # reactive class, or None for main
    entry: Optional[str] = None    # id of the enclosing entry node
    line: int = 0
    order: int = 0                 # source order inside the entry
    branch: Tuple = ()             # ((if-node-id, "T"|"F"), ...)
    # set only on the object-instantiation statements of main, so that the
    # optional relaxation in slicing.py can rebuild the content
    inst: Optional[Tuple[str, str, Tuple[str, ...], str]] = None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: EdgeKind
    label: str = ""                # "true"/"false" on control edges of an if


class RDG:
    def __init__(self, name: str = "rdg"):
        self.name = name
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self._edge_set: Set[Tuple[str, str, EdgeKind, str]] = set()
        self.warnings: List[str] = []
        # statement / actual-in / formal-in node -> the N_SV and N_FP
        # declaration nodes it uses or defines.  Second clause of the
        # observable-slice definition.
        self.var_refs: Dict[str, Set[str]] = {}

    # -- construction -----------------------------------------------------
    def add_node(self, node: Node) -> Node:
        if node.id in self.nodes:
            raise ValueError(f"duplicate RDG node id {node.id!r}")
        self.nodes[node.id] = node
        return node

    def add_edge(self, source: str, target: str, kind: EdgeKind,
                 label: str = "") -> None:
        key = (source, target, kind, label)
        if key in self._edge_set:
            return
        self._edge_set.add(key)
        self.edges.append(Edge(source, target, kind, label))

    # -- queries ----------------------------------------------------------
    def of_kind(self, kind: NodeKind) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind is kind]

    def edges_of(self, kind: EdgeKind) -> List[Edge]:
        return [e for e in self.edges if e.kind is kind]

    def successors(self) -> Dict[str, List[Tuple[str, EdgeKind, str]]]:
        out: Dict[str, List[Tuple[str, EdgeKind, str]]] = {}
        for e in self.edges:
            out.setdefault(e.source, []).append((e.target, e.kind, e.label))
        return out

    def predecessors(self) -> Dict[str, List[Tuple[str, EdgeKind, str]]]:
        out: Dict[str, List[Tuple[str, EdgeKind, str]]] = {}
        for e in self.edges:
            out.setdefault(e.target, []).append((e.source, e.kind, e.label))
        return out

    def induced(self, keep: Set[str], name: Optional[str] = None) -> "RDG":
        sub = RDG(name or f"{self.name}-slice")
        for nid in self.nodes:
            if nid in keep:
                sub.nodes[nid] = self.nodes[nid]
                if nid in self.var_refs:
                    sub.var_refs[nid] = set(self.var_refs[nid])
        for e in self.edges:
            if e.source in keep and e.target in keep:
                sub.add_edge(e.source, e.target, e.kind, e.label)
        return sub


# --------------------------------------------------------------------------
# Flow items -- the linear/branching view of one entry, used for E_D and E_I
# --------------------------------------------------------------------------

@dataclass
class _Item:
    node: str
    defs: Tuple[str, ...] = ()
    uses: Tuple[str, ...] = ()
    then_items: List["_Item"] = field(default_factory=list)
    else_items: List["_Item"] = field(default_factory=list)
    is_if: bool = False


# A definition that flows in from a previous activation of the message
# server rather than from a statement of it.
_INCOMING = "@in:"


class RDGBuilder:
    def __init__(self, model: Model, name: str = "rdg",
                 strict_intra_rebec: bool = False):
        self.model = model
        self.strict_intra_rebec = strict_intra_rebec
        self.g = RDG(name)
        self._counter = 0
        # entry id -> flow items
        self._flow: Dict[str, List[_Item]] = {}
        # (def-node, use-node) -> variables carried by that data edge
        self._data_vars: Dict[Tuple[str, str], Set[str]] = {}
        # entry -> variable -> definitions live where the body ends
        self._exit_defs: Dict[str, Dict[str, Set[str]]] = {}
        # entry -> variable -> uses that read the value the body started with
        self._upward_uses: Dict[str, Dict[str, Set[str]]] = {}

    # -- ids --------------------------------------------------------------
    @staticmethod
    def class_id(cls: str) -> str:
        return f"C:{cls}"

    @staticmethod
    def sv_id(cls: str, var: str) -> str:
        return f"SV:{cls}.{var}"

    @staticmethod
    def entry_id(cls: Optional[str], name: str) -> str:
        return "E:main" if cls is None else f"E:{cls}.{name}"

    @staticmethod
    def fp_id(entry: str, param: str) -> str:
        return f"FP:{entry}.{param}"

    def next_index(self) -> int:
        self._counter += 1
        return self._counter

    # -- top level --------------------------------------------------------
    def build(self) -> RDG:
        self._declarations()
        self._bodies()
        self._data_dependence()
        self._intra_rebec_dependence()
        return self.g

    # -- N_C, N_SV, N_E, N_FP and E_M -------------------------------------
    def _declarations(self) -> None:
        g = self.g
        g.add_node(Node(id=self.entry_id(None, "main"), kind=NodeKind.E,
                        content=("E", "main"), label="main"))
        for klass in self.model.classes:
            cid = self.class_id(klass.name)
            g.add_node(Node(id=cid, kind=NodeKind.C, content=("C", klass.name),
                            label=f"reactiveclass {klass.name}",
                            owner=klass.name, line=klass.line))
            for var in klass.state_vars:
                vid = self.sv_id(klass.name, var.name)
                g.add_node(Node(id=vid, kind=NodeKind.SV,
                                content=("SV", var.name, var.type),
                                label=f"sv_{var.name}",
                                owner=klass.name, line=var.line))
                g.add_edge(cid, vid, EdgeKind.M)
            if klass.constructor is not None:
                eid = self.entry_id(klass.name, "constructor")
                g.add_node(Node(id=eid, kind=NodeKind.E,
                                content=("E", "constructor"),
                                label=f"{klass.name}()",
                                owner=klass.name,
                                line=klass.constructor.line))
                g.add_edge(cid, eid, EdgeKind.M)
                self._formal_params(eid, klass.name, klass.constructor.params)
            for msgsrv in klass.msgsrvs:
                eid = self.entry_id(klass.name, msgsrv.name)
                g.add_node(Node(id=eid, kind=NodeKind.E,
                                content=("E", msgsrv.name),
                                label=f"msgsrv {klass.name}.{msgsrv.name}",
                                owner=klass.name, line=msgsrv.line))
                g.add_edge(cid, eid, EdgeKind.M)
                self._formal_params(eid, klass.name, msgsrv.params)

    def _formal_params(self, entry: str, owner: str,
                       params: Sequence[VarDecl]) -> None:
        for param in params:
            pid = self.fp_id(entry, param.name)
            self.g.add_node(Node(id=pid, kind=NodeKind.FP,
                                 content=("FP", param.name, param.type),
                                 label=f"{param.name} = {param.name}_in",
                                 owner=owner, entry=entry, line=param.line))
            self.g.add_edge(entry, pid, EdgeKind.C)

    # -- N_S, N_AP, E_C, E_A, E_B -----------------------------------------
    def _bodies(self) -> None:
        main_entry = self.entry_id(None, "main")
        items: List[_Item] = []
        for inst in self.model.instances:
            sid = f"S:main.{self.next_index()}"
            self.g.add_node(Node(
                id=sid, kind=NodeKind.S, content=("S", inst.text()),
                label=inst.text(), entry=main_entry, line=inst.line,
                inst=(inst.class_name, inst.rebec_name,
                      tuple(inst.known_args),
                      ", ".join(a.text() for a in inst.ctor_args))))
            self.g.add_edge(main_entry, sid, EdgeKind.C)
            target = self.class_id(inst.class_name)
            if target in self.g.nodes:
                self.g.add_edge(sid, target, EdgeKind.C)
            else:
                self.g.warnings.append(
                    f"line {inst.line}: rebec {inst.rebec_name!r} instantiates "
                    f"unknown class {inst.class_name!r}")
            items.append(_Item(node=sid))
        self._flow[main_entry] = items

        for klass in self.model.classes:
            if klass.constructor is not None:
                entry = self.entry_id(klass.name, "constructor")
                _, body = self._walk(klass.constructor.body, klass, entry, ())
                self._flow[entry] = self._prefix_params(
                    entry, klass.constructor.params) + body
            for msgsrv in klass.msgsrvs:
                entry = self.entry_id(klass.name, msgsrv.name)
                _, body = self._walk(msgsrv.body, klass, entry, ())
                self._flow[entry] = self._prefix_params(
                    entry, msgsrv.params) + body
        self._assign_order()
        self._record_var_refs()

    def _prefix_params(self, entry: str,
                       params: Sequence[VarDecl]) -> List[_Item]:
        """Formal-in nodes act as the first assignments of the entry."""
        items = []
        for param in params:
            pid = self.fp_id(entry, param.name)
            items.append(_Item(node=pid, defs=(param.name,)))
        return items

    def _record_var_refs(self) -> None:
        for entry, items in self._flow.items():
            for item in self._flatten(items):
                node = self.g.nodes[item.node]
                for var in set(item.defs) | set(item.uses):
                    decl = self._declaration_of(var, node.owner, entry)
                    if decl is not None:
                        self.g.var_refs.setdefault(item.node, set()).add(decl)

    def _declaration_of(self, var: str, owner: Optional[str],
                        entry: str) -> Optional[str]:
        """The N_FP or N_SV node a name refers to inside `entry`."""
        fid = self.fp_id(entry, var)
        if fid in self.g.nodes:
            return fid
        if owner is not None:
            vid = self.sv_id(owner, var)
            if vid in self.g.nodes:
                return vid
        return None

    def _assign_order(self) -> None:
        """Node.order is the position in the entry's flow, so that `last
        definition` and `first use` in E_I mean what they say."""
        for items in self._flow.values():
            for position, item in enumerate(self._flatten(items)):
                self.g.nodes[item.node].order = position

    def _walk(self, stmts: Sequence[Stmt], klass: ReactiveClass, entry: str,
              branch: Tuple) -> Tuple[List[str], List[_Item]]:
        """Returns (primary node of each statement, flow items in order)."""
        primaries: List[str] = []
        items: List[_Item] = []
        for stmt in stmts:
            primary, stmt_items = self._statement(stmt, klass, entry, branch)
            primaries.append(primary)
            items.extend(stmt_items)
        return primaries, items

    def _statement(self, stmt: Stmt, klass: ReactiveClass, entry: str,
                   branch: Tuple) -> Tuple[str, List[_Item]]:
        g = self.g
        sid = f"S:{entry}.{self.next_index()}"

        def make(text: str) -> Node:
            node = Node(id=sid, kind=NodeKind.S, content=("S", text),
                        label=text, owner=klass.name, entry=entry,
                        line=stmt.line, branch=branch)
            return g.add_node(node)

        if isinstance(stmt, Assign):
            make(stmt.text())
            self._attach(entry, branch, sid)
            return sid, [_Item(node=sid, defs=(stmt.target,),
                               uses=tuple(stmt.value.uses()))]

        if isinstance(stmt, NonDetAssign):
            make(stmt.text())
            self._attach(entry, branch, sid)
            uses: List[str] = []
            for choice in stmt.choices:
                uses.extend(choice.uses())
            return sid, [_Item(node=sid, defs=(stmt.target,),
                               uses=tuple(uses))]

        if isinstance(stmt, If):
            make(stmt.text())
            self._attach(entry, branch, sid)
            then_primary, then_items = self._walk(
                stmt.then_body, klass, entry, branch + ((sid, "T"),))
            else_primary, else_items = self._walk(
                stmt.else_body, klass, entry, branch + ((sid, "F"),))
            for nid in then_primary:
                g.add_edge(sid, nid, EdgeKind.C, "true")
            for nid in else_primary:
                g.add_edge(sid, nid, EdgeKind.C, "false")
            return sid, [_Item(node=sid, uses=tuple(stmt.cond.uses()),
                               then_items=then_items, else_items=else_items,
                               is_if=True)]

        if isinstance(stmt, Send):
            make(stmt.text())
            self._attach(entry, branch, sid)
            target_entry, target_params = self._resolve_send(stmt, klass)
            ap_items: List[_Item] = []
            for index, arg in enumerate(stmt.args):
                if index < len(target_params):
                    pname = target_params[index].name
                else:
                    pname = f"arg{index + 1}"
                aid = f"AP:{sid}.{index + 1}"
                text = f"{pname}_in = {arg.text()}"
                g.add_node(Node(id=aid, kind=NodeKind.AP, content=("AP", text),
                                label=text, owner=klass.name, entry=entry,
                                line=stmt.line, branch=branch))
                g.add_edge(sid, aid, EdgeKind.C)
                if target_entry is not None and index < len(target_params):
                    fid = self.fp_id(target_entry, target_params[index].name)
                    if fid in g.nodes:
                        g.add_edge(aid, fid, EdgeKind.B)
                ap_items.append(_Item(node=aid, uses=tuple(arg.uses())))
            if target_entry is not None:
                g.add_edge(sid, target_entry, EdgeKind.A)
            after_uses = tuple(stmt.after.uses()) if stmt.after else ()
            return sid, ap_items + [_Item(node=sid, uses=after_uses)]

        raise TypeError(f"unsupported statement {stmt!r}")

    def _attach(self, entry: str, branch: Tuple, sid: str) -> None:
        """Top-level statements hang off the entry; nested ones off their
        conditional, which `_statement` wires up when it builds the branch."""
        if not branch:
            self.g.add_edge(entry, sid, EdgeKind.C)

    def _resolve_send(self, stmt: Send,
                      klass: ReactiveClass) -> Tuple[Optional[str], List[VarDecl]]:
        target_class: Optional[str]
        if stmt.receiver == "self":
            target_class = klass.name
        else:
            target_class = None
            for known in klass.known_rebecs:
                if known.name == stmt.receiver:
                    target_class = known.type
                    break
            if target_class is None:
                target_class = self.model.class_of_rebec(stmt.receiver)
        if target_class is None:
            self.g.warnings.append(
                f"line {stmt.line}: cannot resolve receiver "
                f"{stmt.receiver!r} of {stmt.receiver}.{stmt.message}")
            return None, []
        klass_def = self.model.klass(target_class)
        if klass_def is None:
            self.g.warnings.append(
                f"line {stmt.line}: unknown class {target_class!r}")
            return None, []
        msgsrv = klass_def.msgsrv(stmt.message)
        if msgsrv is None:
            self.g.warnings.append(
                f"line {stmt.line}: class {target_class} has no message "
                f"server {stmt.message!r}")
            return None, []
        return self.entry_id(target_class, msgsrv.name), list(msgsrv.params)

    # -- E_D ---------------------------------------------------------------
    def _data_dependence(self) -> None:
        """Reaching definitions per entry.  Each state variable is seeded with
        a synthetic incoming definition, so that a use reading the value the
        message server started with is recorded as upward exposed; those are
        the targets of the intra-rebec edges."""
        for entry, items in self._flow.items():
            owner = self._entry_owner(entry)
            seed: Dict[str, Set[str]] = {}
            if owner is not None:
                klass = self.model.klass(owner)
                if klass is not None:
                    for var in klass.state_vars:
                        seed[var.name] = {_INCOMING + var.name}
            self._upward_uses[entry] = {}
            exit_state = self._reaching(items, seed, entry)
            self._exit_defs[entry] = {
                var: {d for d in defs if not d.startswith(_INCOMING)}
                for var, defs in exit_state.items()}
        self._def_def_edges()

    def _entry_owner(self, entry: str) -> Optional[str]:
        node = self.g.nodes.get(entry)
        return node.owner if node is not None else None

    def _reaching(self, items: Sequence[_Item], incoming: Dict[str, Set[str]],
                  entry: str) -> Dict[str, Set[str]]:
        """Reaching definitions over a statement list; adds E_D for clause 1
        of the data-dependence definition (def reaches a use with no
        intervening definition)."""
        cur = {var: set(defs) for var, defs in incoming.items()}
        for item in items:
            for var in item.uses:
                for definition in cur.get(var, ()):
                    if definition.startswith(_INCOMING):
                        self._upward_uses.setdefault(entry, {}).setdefault(
                            var, set()).add(item.node)
                        continue
                    self.g.add_edge(definition, item.node, EdgeKind.D)
                    self._data_vars.setdefault(
                        (definition, item.node), set()).add(var)
            if item.is_if:
                then_out = self._reaching(item.then_items, cur, entry)
                else_out = (self._reaching(item.else_items, cur, entry)
                            if item.else_items
                            else {v: set(d) for v, d in cur.items()})
                merged: Dict[str, Set[str]] = {}
                for var in set(then_out) | set(else_out):
                    merged[var] = set(then_out.get(var, set())) | \
                                  set(else_out.get(var, set()))
                cur = merged
            else:
                for var in item.defs:
                    cur[var] = {item.node}
        return cur

    def _def_def_edges(self) -> None:
        """Clause 2: two definitions of the same variable that both reach a
        common use, ordered, and not in different branches of one conditional."""
        by_use: Dict[Tuple[str, str], List[str]] = {}
        for (definition, use), variables in self._data_vars.items():
            for var in variables:
                by_use.setdefault((use, var), []).append(definition)
        for (_use, _var), defs in by_use.items():
            if len(defs) < 2:
                continue
            ordered = sorted(defs, key=lambda nid: self.g.nodes[nid].order)
            for i, first in enumerate(ordered):
                for second in ordered[i + 1:]:
                    if self._exclusive(first, second):
                        continue
                    self.g.add_edge(first, second, EdgeKind.D)

    def _exclusive(self, a: str, b: str) -> bool:
        """True when a and b sit in different branches of the same
        conditional, so they can never both execute."""
        pa, pb = self.g.nodes[a].branch, self.g.nodes[b].branch
        for (if_a, side_a), (if_b, side_b) in zip(pa, pb):
            if if_a != if_b:
                return False
            if side_a != side_b:
                return True
        return False

    # -- E_I ---------------------------------------------------------------
    def _intra_rebec_dependence(self) -> None:
        """Intra-rebec dependence: a state variable written by one activation
        of a message server and read by a later one.

        The article words this as "the last statement of a message server
        which is assigning a value to a variable and the first use of that
        variable in another message server".  Read literally that misses two
        cases, so by default we take the standard reading it is short for:

        * every definition still live where the body ends, not only the
          textually last one -- with a conditional there can be one per branch;
        * a message server may be the target of its own definitions, because a
          rebec handles the same message again later.  Restricting to
          "another" message server drops the dependency of a message server on
          its own previous activation, which is how most Timed Rebeca models
          carry state.

        Pass strict_intra_rebec=True for the literal reading.
        """
        for klass in self.model.classes:
            sources: List[str] = []
            if klass.constructor is not None:
                sources.append(self.entry_id(klass.name, "constructor"))
            targets = [self.entry_id(klass.name, m.name) for m in klass.msgsrvs]
            sources.extend(targets)
            for var in (v.name for v in klass.state_vars):
                for source in sources:
                    if self.strict_intra_rebec:
                        defs = self._last_definition(source, var)
                    else:
                        defs = self._exit_defs.get(source, {}).get(var, set())
                    if not defs:
                        continue
                    for target in targets:
                        if source == target and self.strict_intra_rebec:
                            continue
                        if self.strict_intra_rebec:
                            uses = self._first_use(target, var)
                        else:
                            uses = self._upward_uses.get(target, {}).get(
                                var, set())
                        for definition in defs:
                            for use in uses:
                                self.g.add_edge(definition, use, EdgeKind.I)

    def _last_definition(self, entry: str, var: str) -> Set[str]:
        items = self._flatten(self._flow.get(entry, []))
        defs = [i.node for i in items if var in i.defs]
        if not defs:
            return set()
        return {max(defs, key=lambda nid: self.g.nodes[nid].order)}

    def _first_use(self, entry: str, var: str) -> Set[str]:
        items = self._flatten(self._flow.get(entry, []))
        uses = [i.node for i in items if var in i.uses]
        if not uses:
            return set()
        return {min(uses, key=lambda nid: self.g.nodes[nid].order)}

    def _flatten(self, items: Sequence[_Item]) -> List[_Item]:
        out: List[_Item] = []
        for item in items:
            out.append(item)
            if item.is_if:
                out.extend(self._flatten(item.then_items))
                out.extend(self._flatten(item.else_items))
        return out


def build_rdg(model: Model, name: str = "rdg",
              strict_intra_rebec: bool = False) -> RDG:
    return RDGBuilder(model, name, strict_intra_rebec).build()
