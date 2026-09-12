"""Command line: compare two Timed Rebeca models through their observable
RDG slices, and write both RDGs and the verdict into one output folder."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .compare import Comparison, compare
from .dot import legend_dot, to_dot
from .rdg import EdgeKind, NodeKind, RDG, build_rdg
from .rebeca import Model, RebecaError, parse_file
from .slicing import (ObservableError, Observables, SliceResult,
                      ignore_known_rebecs, observable_slice,
                      parse_observables)

KIND_ORDER = [NodeKind.C, NodeKind.E, NodeKind.S, NodeKind.FP,
              NodeKind.AP, NodeKind.SV]
EDGE_ORDER = [EdgeKind.C, EdgeKind.D, EdgeKind.I, EdgeKind.M,
              EdgeKind.B, EdgeKind.A]


@dataclass
class Side:
    path: str
    stem: str
    model: Model
    graph: RDG
    result: SliceResult

    def counts(self) -> str:
        nodes = ", ".join(
            f"{k.value}={len([n for n in self.graph.nodes.values() if n.kind is k])}"
            for k in KIND_ORDER)
        edges = ", ".join(
            f"{k.value}={len(self.graph.edges_of(k))}" for k in EDGE_ORDER)
        return nodes + "\n    " + edges


def load(path: str, observables: Observables,
         strict_intra_rebec: bool = False,
         observe_parameters: bool = False) -> Side:
    model = parse_file(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    graph = build_rdg(model, stem, strict_intra_rebec=strict_intra_rebec)
    rebec_class = {i.rebec_name: i.class_name for i in model.instances}
    result = observable_slice(graph, observables, rebec_class,
                              name=f"{stem}-slice",
                              observe_parameters=observe_parameters)
    return Side(path, stem, model, graph, result)


def _section(title: str) -> str:
    return f"\n{title}\n{'-' * len(title)}\n"


def build_report(left: Side, right: Side, observables: Observables,
                 verdict: Comparison, options: List[str],
                 cross_check: Optional[str] = None) -> str:
    out: List[str] = []
    out.append("Observable RDG slice comparison")
    out.append("=" * 31)
    out.append("")
    out.append(f"left  model : {left.path}")
    out.append(f"right model : {right.path}")
    out.append(f"observables : {observables.source}")
    out.append(f"              O = {{{observables.text()}}}")
    if observables.ignored:
        out.append(f"              ignored (not message names): "
                   f"{', '.join(observables.ignored)}")
    out.append(f"options     : {', '.join(options) if options else 'defaults'}")

    out.append(_section("VERDICT").rstrip())
    if verdict.equivalent:
        out.append("")
        out.append("  Slice(RDG(left), O) == Slice(RDG(right), O)")
        out.append("")
        out.append("  The two observable slices are EQUIVALENT.")
        out.append("  By the soundness theorem of Section 3, the two models'")
        out.append("  semantic models are weak timed bisimilar with respect")
        out.append("  to O, so a tiny twin built for one of them is valid for")
        out.append("  the other and does not have to be regenerated.")
    else:
        out.append("")
        out.append("  Slice(RDG(left), O) != Slice(RDG(right), O)")
        out.append("")
        out.append("  The two observable slices are NOT EQUIVALENT.")
        out.append("  The check is sound but conservative: a difference here")
        out.append("  does not prove the observable behaviour changed, only")
        out.append("  that this analysis cannot certify it unchanged.")
        out.append("")
        out.append("  Differences found:")
        for reason in verdict.reasons:
            out.append(f"    - {reason}")
    if cross_check:
        out.append("")
        out.append(f"  NOTE: {cross_check}")

    for tag, side in (("left", left), ("right", right)):
        out.append(_section(f"{tag} model: {side.path}").rstrip())
        out.append(f"  reactive classes : "
                   f"{', '.join(c.name for c in side.model.classes)}")
        out.append(f"  rebecs in main   : "
                   f"{', '.join(i.rebec_name for i in side.model.instances)}")
        out.append(f"  RDG              : {len(side.graph.nodes)} nodes, "
                   f"{len(side.graph.edges)} edges")
        out.append(f"    {side.counts()}")
        sliced = side.result.graph
        share = (100.0 * len(sliced.nodes) / len(side.graph.nodes)
                 if side.graph.nodes else 0.0)
        out.append(f"  Slice(RDG,O)     : {len(sliced.nodes)} nodes, "
                   f"{len(sliced.edges)} edges  ({share:.1f}% of the RDG)")
        out.append(f"  relevant variables RV : "
                   f"{', '.join(side.result.relevant_variables()) or '(none)'}")
        out.append(f"  relevant messages  RM : "
                   f"{', '.join(side.result.relevant_messages()) or '(none)'}")
        outside = [n for n in side.graph.nodes.values()
                   if n.id not in side.result.kept]
        if outside:
            out.append("  outside the slice     :")
            for node in sorted(outside, key=lambda n: (n.kind.value, n.order,
                                                       n.id)):
                out.append(f"      {node.kind.value:5s} {node.label}")
        else:
            out.append("  outside the slice     : (nothing -- the whole RDG "
                       "is relevant to O)")
        if side.result.unmatched:
            out.append(f"  WARNING: no message server matched "
                       f"{', '.join(side.result.unmatched)}")
        for warning in side.graph.warnings:
            out.append(f"  WARNING: {warning}")

    out.append("")
    return "\n".join(out) + "\n"


def run(model1: str, model2: str, observable_file: str, out_dir: str,
        quiet: bool = False, verbose: bool = False,
        strict_main_args: bool = False,
        strict_intra_rebec: bool = False,
        observe_parameters: bool = False) -> int:
    observables = parse_observables(observable_file)
    left = load(model1, observables, strict_intra_rebec, observe_parameters)
    right = load(model2, observables, strict_intra_rebec, observe_parameters)
    if left.stem == right.stem:
        left.stem, right.stem = f"{left.stem}-1", f"{right.stem}-2"

    options: List[str] = []
    if strict_intra_rebec:
        options.append("--strict-intra-rebec")
    if strict_main_args:
        options.append("--strict-main-args")
    if observe_parameters:
        options.append("--observe-parameters")

    for tag, side in (("first", left), ("second", right)):
        if not side.result.roots:
            available = sorted({n.content[1] for n in side.graph.nodes.values()
                                if n.kind is NodeKind.E
                                and n.content[1] not in ("main", "constructor")})
            raise ObservableError(
                f"none of the observable messages exists in the {tag} model "
                f"({side.path}), so its slice is empty and any comparison "
                f"would be vacuous.\n  asked for : {observables.text()}\n"
                f"  available : {', '.join(available)}")

    compared_left, compared_right = left.result.graph, right.result.graph
    if not strict_main_args:
        compared_left = ignore_known_rebecs(compared_left, left.graph)
        compared_right = ignore_known_rebecs(compared_right, right.graph)
    verdict = compare(compared_left, compared_right,
                      left.stem, right.stem)

    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    def write(name: str, text: str) -> None:
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        written.append(path)

    for side in (left, right):
        write(f"{side.stem}-rdg.dot",
              to_dot(side.graph, side.result.kept, side.result.roots,
                     model=side.stem))
        write(f"{side.stem}-slice.dot",
              to_dot(side.result.graph, set(side.result.graph.nodes),
                     side.result.roots, model=f"{side.stem}-slice"))
    cross_check = _cross_check(model1, model2, observables, verdict,
                               strict_main_args, strict_intra_rebec,
                               observe_parameters)
    write("legend.dot", legend_dot())
    report = build_report(left, right, observables, verdict, options,
                          cross_check)
    write("result.txt", report)

    if verbose:
        print(report)
    elif not quiet:
        print(summary(left, right, observables, verdict, out_dir, written))
    return 0 if verdict.equivalent else 1


def summary(left: Side, right: Side, observables: Observables,
            verdict: Comparison, out_dir: str, written: List[str]) -> str:
    """The short form printed to the terminal.  result.txt keeps the rest."""
    out: List[str] = [""]
    out.append(f"O = {observables.text()}")
    out.append("")
    for side in (left, right):
        whole, sliced = side.graph, side.result.graph
        share = (100.0 * len(sliced.nodes) / len(whole.nodes)
                 if whole.nodes else 0.0)
        out.append(f"  {side.stem:<24} RDG {len(whole.nodes):4d} nodes"
                   f"   slice {len(sliced.nodes):4d}  ({share:.0f}%)")
    out.append("")
    out.append(f"  {verdict.verdict}")
    if not verdict.equivalent:
        for reason in verdict.reasons[:4]:
            out.append(f"    {reason}")
        if len(verdict.reasons) > 4:
            out.append(f"    ... and {len(verdict.reasons) - 4} more")
    for side in (left, right):
        for text in side.result.unmatched:
            out.append(f"    warning: nothing in {side.stem} is named {text}")
        for text in side.graph.warnings:
            out.append(f"    warning: {side.stem}: {text}")
    out.append("")
    out.append(f"  {len(written)} files in {out_dir}/ -- details in "
               f"result.txt")
    out.append("")
    return "\n".join(out)


def _cross_check(model1: str, model2: str, observables: Observables,
                 verdict: Comparison, strict_main_args: bool,
                 strict_intra_rebec: bool,
                 observe_parameters: bool) -> Optional[str]:
    """The article's text and its own worked examples disagree in two places,
    each behind a flag.  Say so when the other reading would flip the answer,
    rather than leaving the reader to discover it."""
    other = not strict_intra_rebec
    try:
        a = load(model1, observables, other, observe_parameters)
        b = load(model2, observables, other, observe_parameters)
    except Exception:                    # never let the note break the run
        return None
    left_graph, right_graph = a.result.graph, b.result.graph
    if not strict_main_args:
        left_graph = ignore_known_rebecs(left_graph, a.graph)
        right_graph = ignore_known_rebecs(right_graph, b.graph)
    alternative = compare(left_graph, right_graph)
    if alternative.equivalent == verdict.equivalent:
        return None
    flag = ("without --strict-intra-rebec" if strict_intra_rebec
            else "with --strict-intra-rebec")
    return (f"the other reading of the intra-rebec edge ({flag}) gives "
            f"{alternative.verdict} instead.  See the README section "
            f"'Where the article's text and its examples disagree'.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rdgcompare",
        description="Compare two Timed Rebeca models by their observable RDG "
                    "slices.  Writes both RDGs as Graphviz .dot files and the "
                    "verdict as result.txt into one output folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit status: 0 the slices are equivalent, 1 they are not, "
               "2 the input could not be read")
    parser.add_argument("model1", help="first Timed Rebeca model (.rebeca)")
    parser.add_argument("model2", help="second Timed Rebeca model (.rebeca)")
    parser.add_argument("observables",
                        help="file listing the observable message names")
    parser.add_argument("-o", "--output", default="out",
                        help="output folder (default: out)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="print only the verdict")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print the whole of result.txt instead of a "
                             "summary")
    parser.add_argument("--strict-intra-rebec", action="store_true",
                        help="read the intra-rebec edge definition literally: "
                             "only the textually last assignment, and only to "
                             "a different message server.  Off by default "
                             "because it misses a message server's dependency "
                             "on its own previous activation")
    parser.add_argument("--observe-parameters", action="store_true",
                        help="also treat the arguments of the observable "
                             "messages as observable, by adding their "
                             "formal-in nodes to the roots of the slice")
    parser.add_argument("--strict-main-args", action="store_true",
                        help="keep the known rebecs inside the content of an "
                             "object-instantiation statement in main.  Off by "
                             "default because Section 3 says the RDG ignores "
                             "known rebecs")
    args = parser.parse_args(argv)

    try:
        status = run(args.model1, args.model2, args.observables,
                     args.output, args.quiet, args.verbose,
                     strict_main_args=args.strict_main_args,
                     strict_intra_rebec=args.strict_intra_rebec,
                     observe_parameters=args.observe_parameters)
    except (RebecaError, ObservableError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.quiet:
        print("EQUIVALENT" if status == 0 else "NOT EQUIVALENT")
    return status
