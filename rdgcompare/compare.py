"""RDG equivalence: Definition "RDG Equivalence" of Section 3.

Two RDGs are equivalent when there is a bijection phi between their nodes that
preserves the kind and the content of every node and preserves every edge
relation.  The article lists the edge conditions one kind at a time (member
edges from class-object nodes, control edges from entries, activation edges
from sends, and so on); we require the whole edge set to correspond, including
the binding and intra-rebec edges and the true/false labels of the control
edges out of a conditional, so the check is at least as strong as the
definition and never reports a difference that is not there.

The bijection is searched for by colour refinement followed by backtracking.
No third-party dependency.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .rdg import RDG, EdgeKind, Node, NodeKind

MAX_SEARCH_STEPS = 2_000_000


@dataclass
class Comparison:
    equivalent: bool
    reasons: List[str] = field(default_factory=list)
    mapping: Dict[str, str] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        return "EQUIVALENT" if self.equivalent else "NOT EQUIVALENT"


def _signature(node: Node) -> Tuple:
    return (node.kind.value,) + tuple(node.content)


def _refine(graph: RDG) -> Dict[str, Tuple]:
    incoming: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    outgoing: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for edge in graph.edges:
        key = f"{edge.kind.value}:{edge.label}"
        outgoing[edge.source].append((key, edge.target))
        incoming[edge.target].append((key, edge.source))

    colour: Dict[str, Tuple] = {
        nid: _signature(node) for nid, node in graph.nodes.items()}
    for _ in range(len(graph.nodes) + 1):
        nxt: Dict[str, Tuple] = {}
        for nid in graph.nodes:
            out = tuple(sorted((k, colour[t]) for k, t in outgoing.get(nid, ())))
            inn = tuple(sorted((k, colour[s]) for k, s in incoming.get(nid, ())))
            nxt[nid] = (colour[nid], out, inn)
        if len(set(nxt.values())) == len(set(colour.values())):
            return nxt
        colour = nxt
    return colour


def _edge_key_set(graph: RDG, mapping: Dict[str, str]) -> Set[Tuple[str, str, str, str]]:
    return {(mapping[e.source], mapping[e.target], e.kind.value, e.label)
            for e in graph.edges}


def _describe_content(node_kind: str, signature: Tuple) -> str:
    # signature is (node kind, content tag, ...), and the content tag repeats
    # the node kind, so it is dropped here.
    return f"{node_kind} {' '.join(str(c) for c in signature[2:])}"


def _content_differences(left: RDG, right: RDG, left_name: str,
                         right_name: str) -> List[str]:
    reasons: List[str] = []
    counts: List[str] = []

    left_kinds = Counter(n.kind.value for n in left.nodes.values())
    right_kinds = Counter(n.kind.value for n in right.nodes.values())
    for kind in sorted(set(left_kinds) | set(right_kinds)):
        if left_kinds[kind] != right_kinds[kind]:
            counts.append(
                f"{kind}: {left_kinds[kind]} node(s) in {left_name}, "
                f"{right_kinds[kind]} in {right_name}")

    left_edges = Counter(e.kind.value for e in left.edges)
    right_edges = Counter(e.kind.value for e in right.edges)
    for kind in sorted(set(left_edges) | set(right_edges)):
        if left_edges[kind] != right_edges[kind]:
            counts.append(
                f"{kind}: {left_edges[kind]} edge(s) in {left_name}, "
                f"{right_edges[kind]} in {right_name}")

    left_content = Counter(_signature(n) for n in left.nodes.values())
    right_content = Counter(_signature(n) for n in right.nodes.values())
    only_left = left_content - right_content
    only_right = right_content - left_content
    for signature, count in sorted(only_left.items(), key=lambda kv: str(kv[0])):
        times = f" ({count}x)" if count > 1 else ""
        reasons.append(f"only in {left_name}{times}: "
                       f"{_describe_content(signature[0], signature)}")
    for signature, count in sorted(only_right.items(), key=lambda kv: str(kv[0])):
        times = f" ({count}x)" if count > 1 else ""
        reasons.append(f"only in {right_name}{times}: "
                       f"{_describe_content(signature[0], signature)}")
    return reasons + counts


def compare(left: RDG, right: RDG, left_name: str = "the left",
            right_name: str = "the right") -> Comparison:
    reasons = _content_differences(left, right, left_name, right_name)
    if reasons:
        return Comparison(False, reasons)

    left_colour = _refine(left)
    right_colour = _refine(right)
    if Counter(left_colour.values()) != Counter(right_colour.values()):
        return Comparison(False, [
            "the two slices have the same nodes and the same number of edges "
            "of each kind, but no bijection preserves the dependencies: the "
            "structure around at least one node differs"])

    buckets: Dict[Tuple, List[str]] = defaultdict(list)
    for nid, colour in right_colour.items():
        buckets[colour].append(nid)
    for value in buckets.values():
        value.sort()

    ordered = sorted(left.nodes, key=lambda nid: (
        len(buckets[left_colour[nid]]), str(left_colour[nid]), nid))

    left_out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    left_in: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for edge in left.edges:
        key = f"{edge.kind.value}:{edge.label}"
        left_out[edge.source].append((key, edge.target))
        left_in[edge.target].append((key, edge.source))
    right_edges = {(e.source, e.target, e.kind.value, e.label)
                   for e in right.edges}

    mapping: Dict[str, str] = {}
    used: Set[str] = set()
    steps = 0
    overflow = False

    def consistent(node: str, image: str) -> bool:
        for key, target in left_out.get(node, ()):
            if target in mapping:
                kind, _, label = key.partition(":")
                if (image, mapping[target], kind, label) not in right_edges:
                    return False
        for key, source in left_in.get(node, ()):
            if source in mapping:
                kind, _, label = key.partition(":")
                if (mapping[source], image, kind, label) not in right_edges:
                    return False
        return True

    def search(index: int) -> bool:
        nonlocal steps, overflow
        if index == len(ordered):
            return True
        if steps > MAX_SEARCH_STEPS:
            overflow = True
            return False
        node = ordered[index]
        for image in buckets[left_colour[node]]:
            if image in used:
                continue
            steps += 1
            if not consistent(node, image):
                continue
            mapping[node] = image
            used.add(image)
            if search(index + 1):
                return True
            del mapping[node]
            used.discard(image)
        return False

    if not search(0):
        if overflow:
            return Comparison(False, [
                "the search for a bijection did not finish within the step "
                "limit, so the verdict is inconclusive; treat it as not "
                "equivalent"])
        return Comparison(False, [
            "the two slices have matching nodes but no bijection preserves "
            "all dependency edges"])

    if _edge_key_set(left, mapping) != right_edges:
        return Comparison(False, [
            "the bijection found does not carry every edge across; the "
            "dependency structures differ"])
    return Comparison(True, [], dict(mapping))
