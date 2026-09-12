"""Graphviz DOT rendering of an RDG, in the style of the RDG figures drawn
for the article (see 20/new-rdg-legends.dot).

    * boxes for everything, an ellipse for a class-object node
    * an HTML label of the form  <number><BR/><syntax>
    * one cluster per reactive class, labelled Model$Class, plus one for main
    * nodes of the observable slice are filled: the observable message-server
      entries orange, the main entry green, everything else yellow; nodes
      outside the slice are left unfilled
    * edges carry no labels; the colour says which dependence it is, and a
      legend inside the graph gives the key

Edge colours, as in the reference figure and in the same order the article
introduces them:

    member      green
    control     black
    data        blue
    intra-rebec blue dotted
    activation  black, unconstrained
    binding     purple, unconstrained
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from .rdg import EdgeKind, Node, NodeKind, RDG

EDGE_STYLE = {
    EdgeKind.M: dict(attrs='color="green"', title="member dependence"),
    EdgeKind.C: dict(attrs="", title="control dependence"),
    EdgeKind.D: dict(attrs='color="blue"', title="data dependence"),
    EdgeKind.I: dict(attrs='color="blue", style="dotted"',
                     title="intra-rebec dependence"),
    EdgeKind.A: dict(attrs="constraint=false", title="activation dependence"),
    EdgeKind.B: dict(attrs='color="purple", constraint=false',
                     title="binding dependence"),
}

# the order the legend lists them in
LEGEND_ORDER = [EdgeKind.M, EdgeKind.C, EdgeKind.D, EdgeKind.I,
                EdgeKind.A, EdgeKind.B]

FILL_MAIN = "green"
FILL_OBSERVABLE = "orange"
FILL_SLICE = "yellow"


def _html(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _cluster_key(node: Node) -> str:
    return node.owner or ""


def _sort_key(node: Node) -> tuple:
    kind_rank = {NodeKind.C: 0, NodeKind.SV: 1, NodeKind.E: 2,
                 NodeKind.FP: 3, NodeKind.S: 4, NodeKind.AP: 5}
    return (kind_rank[node.kind], node.entry or "", node.order, node.line,
            node.id)


def to_dot(graph: RDG, slice_nodes: Optional[Set[str]] = None,
           observable: Optional[Set[str]] = None,
           model: Optional[str] = None,
           legend: bool = True) -> str:
    slice_nodes = slice_nodes if slice_nodes is not None else set(graph.nodes)
    observable = observable or set()
    model = model or graph.name

    clusters: Dict[str, List[Node]] = {}
    for node in graph.nodes.values():
        clusters.setdefault(_cluster_key(node), []).append(node)

    # number the nodes in the order they are emitted
    order: List[Node] = []
    for owner in [""] + sorted(k for k in clusters if k):
        order.extend(sorted(clusters.get(owner, []), key=_sort_key))
    number = {node.id: index + 1 for index, node in enumerate(order)}

    lines: List[str] = [f'digraph "{_quote(model)}" {{',
                        "compound=true;",
                        'node [shape="rect"];',
                        ""]

    def emit(owner: str) -> None:
        nodes = sorted(clusters.get(owner, []), key=_sort_key)
        if not nodes:
            return
        label = model if not owner else f"{model}${owner}"
        safe = "".join(c if c.isalnum() else "_" for c in (owner or "main"))
        lines.append(f'subgraph "cluster_{safe}" {{')
        lines.append(f'  label="{_quote(label)}";')
        lines.append("")
        for node in nodes:
            shape = ' shape="ellipse",' if node.kind is NodeKind.C else ""
            fill = ""
            if node.id in slice_nodes:
                colour = (FILL_OBSERVABLE if node.id in observable
                          else FILL_MAIN if node.content == ("E", "main")
                          else FILL_SLICE)
                fill = f' style="filled", fillcolor="{colour}",'
            lines.append(
                f'  "{_quote(node.id)}" [{shape}{fill} '
                f'label=<{number[node.id]}<BR/>{_html(node.label)}>]')
        lines.append("}")
        lines.append("")

    emit("")
    for owner in sorted(k for k in clusters if k):
        emit(owner)

    for kind in LEGEND_ORDER:
        edges = sorted((e for e in graph.edges if e.kind is kind),
                       key=lambda e: (number.get(e.source, 0),
                                      number.get(e.target, 0), e.label))
        if not edges:
            continue
        style = EDGE_STYLE[kind]
        lines.append("/* " + style["title"] + " */")
        for edge in edges:
            attrs = style["attrs"]
            rendered = f' [{attrs}]' if attrs else ""
            lines.append(f'"{_quote(edge.source)}" -> '
                         f'"{_quote(edge.target)}"{rendered}')
        lines.append("")

    if legend:
        lines.extend(_legend_cluster())
    lines.append("}")
    return "\n".join(lines) + "\n"


def _legend_cluster() -> List[str]:
    lines = ['subgraph "cluster_edge_legend" {',
             '  label="Dependency edges";',
             "",
             '  node [shape="plaintext"];']
    names = [(kind, EDGE_STYLE[kind]["title"].split()[0]) for kind in LEGEND_ORDER]
    for kind, short in names:
        lines.append(f'  "legend_{short}_text" '
                     f'[label="{EDGE_STYLE[kind]["title"]}"];')
    lines.append("")
    for _kind, short in names:
        lines.append(f'  "legend_{short}_start" '
                     f'[shape="point", width=0.03, label=""];')
        lines.append(f'  "legend_{short}_end" '
                     f'[shape="point", width=0.03, label=""];')
    lines.append("")
    for _kind, short in names:
        lines.append(f'  {{ rank=same; "legend_{short}_text"; '
                     f'"legend_{short}_start"; "legend_{short}_end"; }}')
    lines.append("")
    for kind, short in names:
        attrs = EDGE_STYLE[kind]["attrs"].replace(", constraint=false", "") \
                                         .replace("constraint=false", "")
        rendered = f' [{attrs}]' if attrs.strip() else ""
        lines.append(f'  "legend_{short}_start" -> '
                     f'"legend_{short}_end"{rendered};')
    lines.append("")
    chain = " -> ".join(f'"legend_{short}_text"' for _k, short in names)
    lines.append(f'  {chain}')
    lines.append('    [style="invis"];')
    lines.append("}")
    return lines


def legend_dot() -> str:
    """The same key, on its own, for use as a standalone figure."""
    lines = ['digraph "rdg-legend" {',
             "compound=true;",
             'node [shape="rect"];',
             "",
             'subgraph "cluster_node_legend" {',
             '  label="Node kinds";',
             '  "n_C" [shape="ellipse", style="filled", fillcolor="yellow", '
             'label=<N_C<BR/>reactiveclass C>]',
             '  "n_E" [style="filled", fillcolor="yellow", '
             'label=<N_E<BR/>msgsrv m(int x)>]',
             '  "n_Eobs" [style="filled", fillcolor="orange", '
             'label=<N_E<BR/>observable msgsrv>]',
             '  "n_Emain" [style="filled", fillcolor="green", '
             'label=<N_E<BR/>main>]',
             '  "n_SV" [style="filled", fillcolor="yellow", '
             'label=<N_SV<BR/>sv_x>]',
             '  "n_FP" [style="filled", fillcolor="yellow", '
             'label=<N_FP<BR/>x = x_in>]',
             '  "n_AP" [style="filled", fillcolor="yellow", '
             'label=<N_AP<BR/>x_in = e>]',
             '  "n_S" [style="filled", fillcolor="yellow", '
             'label=<N_S<BR/>x = e>]',
             '  "n_out" [label=<outside the slice<BR/>(not filled)>]',
             '  "n_C" -> "n_E" -> "n_Eobs" -> "n_Emain" -> "n_SV" -> "n_FP" '
             '-> "n_AP" -> "n_S" -> "n_out" [style="invis"];',
             "}",
             ""]
    lines.extend(_legend_cluster())
    lines.append("}")
    return "\n".join(lines) + "\n"
