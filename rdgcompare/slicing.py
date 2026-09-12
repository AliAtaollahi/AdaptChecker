"""Observable message sets, the observable RDG slice, and the relevant
variables and message names of Section 3 of the article.

    Slice(G, O) = (N', E')
    N' = { n in N | exists n_m in node(G,O) . n ->* n_m }
         u { v in N_SV u N_FP | some statement of the slice uses or defines v }
    E' = { (n1,n2) in E | n1 in N' and n2 in N' }

    RV(M,O) = Slice(RDG(M),O).N_SV u Slice(RDG(M),O).N_FP
    RM(M,O) = { cont(n) | n in Slice(RDG(M),O).N_E, cont(n) a message name }
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .rdg import RDG, Node, NodeKind


class ObservableError(Exception):
    pass


@dataclass
class Observables:
    """A parsed observable-message file."""
    entries: List[Tuple[Optional[str], str]] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)
    source: str = "<input>"

    def names(self) -> List[str]:
        seen, out = set(), []
        for _owner, message in self.entries:
            if message not in seen:
                seen.add(message)
                out.append(message)
        return out

    def text(self) -> str:
        return ", ".join(f"{o}.{m}" if o else m for o, m in self.entries)


_ENTRY_RE = re.compile(
    r"^(?:(?P<owner>[A-Za-z_][A-Za-z_0-9]*)\s*\.\s*)?"
    r"(?P<message>[A-Za-z_][A-Za-z_0-9]*)"
    r"(?:\s*\([^)]*\))?$")

# Conventions carried over from the tiny-twin tooling that are not message
# names, so they select nothing here.
_NOT_A_MESSAGE = {"time", "tau"}


def parse_observables(path: str) -> Observables:
    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    return parse_observable_text(raw, path)


def parse_observable_text(raw: str, source: str = "<input>") -> Observables:
    result = Observables(source=source)
    for line in raw.splitlines():
        line = line.split("#", 1)[0].split("//", 1)[0].strip()
        if not line:
            continue
        for token in line.split(","):
            token = token.strip()
            if not token:
                continue
            if token.lower() in _NOT_A_MESSAGE:
                result.ignored.append(token)
                continue
            match = _ENTRY_RE.match(token)
            if match is None:
                raise ObservableError(
                    f"{source}: cannot read observable entry {token!r}; "
                    f"expected 'message', 'Class.message' or 'rebec.message'")
            result.entries.append(
                (match.group("owner"), match.group("message")))
    if not result.entries:
        raise ObservableError(f"{source}: no observable message named")
    return result


def formal_in_nodes(graph: RDG, entries: Set[str]) -> Set[str]:
    """The formal-in parameter nodes of the given entry nodes."""
    return {node.id for node in graph.nodes.values()
            if node.kind is NodeKind.FP and node.entry in entries}


def observable_entry_nodes(graph: RDG, observables: Observables,
                           rebec_class: Optional[Dict[str, str]] = None
                           ) -> Tuple[Set[str], List[str]]:
    """node(G, O): the entry nodes of the observable message servers.

    A bare `m` selects every message server named `m`, which is what the
    article's definition says.  A qualified `Class.m` or `rebec.m` narrows it
    to one reactive class, which is how the shipped observable files are
    written; the owner is matched case-insensitively against class names and
    against rebec names declared in main.
    """
    rebec_class = rebec_class or {}
    lowered = {name.lower(): cls for name, cls in rebec_class.items()}
    roots: Set[str] = set()
    unmatched: List[str] = []
    for owner, message in observables.entries:
        target_class = None
        if owner is not None:
            target_class = owner
            for node in graph.of_kind(NodeKind.C):
                if node.content[1].lower() == owner.lower():
                    target_class = node.content[1]
                    break
            else:
                if owner.lower() in lowered:
                    target_class = lowered[owner.lower()]

        def entries_named(exact: bool) -> Set[str]:
            found = set()
            for node in graph.of_kind(NodeKind.E):
                name = node.content[1]
                same = (name == message if exact
                        else name.lower() == message.lower())
                if not same:
                    continue
                if target_class is not None and node.owner != target_class:
                    continue
                found.add(node.id)
            return found

        # Exact first; fall back to a case-insensitive match, because the
        # observable files written for the tiny-twin tooling are lowercased
        # while the message servers are not.
        found = entries_named(True) or entries_named(False)
        if found:
            roots |= found
        else:
            unmatched.append(f"{owner}.{message}" if owner else message)
    return roots, unmatched


def slice_graph(graph: RDG, roots: Set[str]) -> Set[str]:
    """Backward reachability from the observable entries, then the variable
    declarations the reached statements use or define."""
    reverse: Dict[str, List[str]] = {}
    for edge in graph.edges:
        reverse.setdefault(edge.target, []).append(edge.source)

    keep: Set[str] = set()
    stack = [r for r in roots if r in graph.nodes]
    keep.update(stack)
    while stack:
        current = stack.pop()
        for previous in reverse.get(current, ()):
            if previous not in keep:
                keep.add(previous)
                stack.append(previous)

    declarations: Set[str] = set()
    for nid in keep:
        for decl in graph.var_refs.get(nid, ()):
            declarations.add(decl)
    keep |= declarations
    return keep


@dataclass
class SliceResult:
    graph: RDG                       # the induced Slice(G, O)
    kept: Set[str]                   # node ids of the slice
    roots: Set[str]                  # node(G, O)
    unmatched: List[str]             # observable entries that matched nothing

    def relevant_variables(self) -> List[str]:
        out = []
        for node in self.graph.nodes.values():
            if node.kind is NodeKind.SV:
                out.append(f"{node.owner or '?'}.{node.content[1]}")
            elif node.kind is NodeKind.FP:
                entry = (node.entry or "").split(":", 1)[-1]
                out.append(f"{entry}.{node.content[1]}")
        return sorted(set(out))

    def relevant_messages(self) -> List[str]:
        out = []
        for node in self.graph.nodes.values():
            if node.kind is NodeKind.E and node.content[1] not in (
                    "main", "constructor"):
                out.append(node.content[1])
        return sorted(set(out))


def observable_slice(graph: RDG, observables: Observables,
                     rebec_class: Optional[Dict[str, str]] = None,
                     name: Optional[str] = None,
                     observe_parameters: bool = False) -> SliceResult:
    """Slice(G, O).

    With observe_parameters the formal-in nodes of the observable message
    servers join the roots, so backward reachability also pulls in the
    actual-in nodes that supply their arguments and everything those depend
    on.  Off by default: the transition label of the operational semantics is
    the message name, and the article's own example turns on the argument of
    an observable message being irrelevant when the body ignores it.  Turn it
    on to compare models whose observable actions carry their parameters, the
    way tiny-twin labels do.
    """
    roots, unmatched = observable_entry_nodes(graph, observables, rebec_class)
    if observe_parameters:
        roots = roots | formal_in_nodes(graph, roots)
    kept = slice_graph(graph, roots)
    return SliceResult(graph=graph.induced(kept, name), kept=kept,
                       roots=roots, unmatched=unmatched)


def ignore_known_rebecs(sliced: RDG, whole: RDG) -> RDG:
    """Drop the known rebecs an instantiation statement in `main` binds, when
    their reactive class lies outside the slice, before comparing contents.

    Section 3 says the RDG is simpler than its ancestor "due to ignoring known
    rebecs".  Nothing in the graph represents the wiring: a send resolves to
    the *class* of its receiver, so the activation edge points at a class's
    message server, not at a rebec.  Keeping the known rebecs inside the text
    of the instantiation statement would smuggle back in, through cont(), the
    one thing the definition says it leaves out -- and it is what made the
    heater pair of Section 4 compare unequal when the article says it should
    not.

    Known rebecs whose class *is* in the slice are kept, so a genuine
    rewiring among the rebecs that matter is still visible.  The display label
    always shows the statement as written.
    """
    inside = {node.content[1] for node in sliced.nodes.values()
              if node.kind is NodeKind.C}
    external = set()
    for node in whole.nodes.values():
        if node.kind is NodeKind.S and node.inst is not None:
            class_name, rebec_name, _known, _ctor = node.inst
            if class_name not in inside:
                external.add(rebec_name)

    relaxed = RDG(sliced.name)
    for nid, node in sliced.nodes.items():
        if node.kind is NodeKind.S and node.inst is not None:
            class_name, rebec_name, known, ctor = node.inst
            kept_args = [a for a in known if a not in external]
            text = f"{class_name} {rebec_name}({', '.join(kept_args)}):({ctor})"
            node = replace(node, content=("S", text))
        relaxed.nodes[nid] = node
        if nid in sliced.var_refs:
            relaxed.var_refs[nid] = set(sliced.var_refs[nid])
    for edge in sliced.edges:
        relaxed.add_edge(edge.source, edge.target, edge.kind, edge.label)
    return relaxed
