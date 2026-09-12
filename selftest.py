#!/usr/bin/env python3
"""Self-test: `python3 selftest.py`.  No pytest, no third-party package.

The checks pin the facts the article itself states about its examples, so a
change that breaks the correspondence with Section 3 fails here.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rdgcompare.cli import load, run
from rdgcompare.compare import compare
from rdgcompare.rdg import EdgeKind, NodeKind, build_rdg
from rdgcompare.rebeca import RebecaError, parse_file, parse_source
from rdgcompare.slicing import (ObservableError, observable_slice,
                                parse_observable_text, parse_observables,
                                ignore_known_rebecs)

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(HERE, "examples")

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  ok    {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))


def graph_of(path):
    model = parse_file(path)
    return model, build_rdg(model, os.path.basename(path))


def slice_of(path, observable_text, strict=False):
    model = parse_file(path)
    graph = build_rdg(model, os.path.basename(path),
                      strict_intra_rebec=strict)
    rebec_class = {i.rebec_name: i.class_name for i in model.instances}
    return graph, observable_slice(
        graph, parse_observable_text(observable_text), rebec_class)


def edge_labels(graph, kind):
    return {(graph.nodes[e.source].label, graph.nodes[e.target].label)
            for e in graph.edges if e.kind is kind}


def main():
    print("Parsing")
    model, graph = graph_of(os.path.join(EX, "ab-1.rebeca"))
    check("ab-1 has classes A and B",
          [c.name for c in model.classes] == ["A", "B"])
    check("ab-1 declares rebecs a and b",
          [i.rebec_name for i in model.instances] == ["a", "b"])
    check("delay is rejected as outside the fragment",
          rejects("reactiveclass A(1){ A(){ delay(3); } } main{ A a():();}"))
    check("an implicit self-send parses",
          parse_source("reactiveclass A(1){ A(){ m(); } msgsrv m(){} }"
                       " main{ A a():();}") is not None)
    check("a nondeterministic choice may be a send argument",
          parse_source("reactiveclass A(1){ A(){ m(?(1,2)); }"
                       " msgsrv m(int x){} } main{ A a():();}") is not None)
    check("a rebec may be named delay",
          parse_source("reactiveclass B(1){ msgsrv go(){} }"
                       " reactiveclass A(1){ knownrebecs{ B delay; }"
                       " A(){ delay.go(); } } "
                       "main{ A a(delay):(); B delay():();}") is not None)

    print("\nRDG of the article's Figure 1 (Example after the RDG definition)")
    data = edge_labels(graph, EdgeKind.D)
    check("data edge  y = x  ->  if (y)", ("y = x", "if (y)") in data)
    check("data edge  x = !x  ->  z_in = x || y",
          ("x = !x", "z_in = x || y") in data)
    check("binding edge  z_in = x || y  ->  z = z_in",
          ("z_in = x || y", "z = z_in") in edge_labels(graph, EdgeKind.B))
    check("intra-rebec edge  x = true  ->  y = x",
          ("x = true", "y = x") in edge_labels(graph, EdgeKind.I))
    check("activation edge  b.m2() after(0)  ->  msgsrv B.m2",
          ("b.m2() after(0)", "msgsrv B.m2") in edge_labels(graph, EdgeKind.A))
    check("a send with no after annotation is normalised to after(0), so it "
          "compares equal to one written out",
          any(lbl == "b.m2() after(0)"
              for lbl in (n.label for n in graph.nodes.values())))
    branch = {(graph.nodes[e.source].label, e.label,
               graph.nodes[e.target].label)
              for e in graph.edges if e.kind is EdgeKind.C and e.label}
    check("control edges out of a conditional carry true/false",
          ("if (y)", "true", "self.m2() after(5)") in branch
          and ("if (y)", "false", "a.m1() after(0)") in branch)
    check("a conditional controls the send, not its actual-in node",
          not any(src == "if (y)" and tgt.endswith("_in = x || y")
                  for src, _lbl, tgt in branch))

    print("\nObservable slice of the article's Figure 2 (the revision)")
    whole, result = slice_of(os.path.join(EX, "ab-2.rebeca"), "m1", strict=True)
    outside = sorted(n.label for n in whole.nodes.values()
                     if n.id not in result.kept)
    expected = sorted(["z_in = true", "z_in = x || y", "z = z_in", "x = !x"])
    check("with --strict-intra-rebec, exactly the four nodes the article "
          "names fall outside the slice", outside == expected, f"got {outside}")
    whole, result = slice_of(os.path.join(EX, "ab-2.rebeca"), "m1")
    outside = sorted(n.label for n in whole.nodes.values()
                     if n.id not in result.kept)
    check("by default x = !x stays in, because m2 reads x on its next "
          "activation",
          outside == sorted(["z_in = true", "z_in = x || y", "z = z_in"]),
          f"got {outside}")
    check("the parameter z drops out of the relevant variables",
          "A.m1.z" not in result.relevant_variables(),
          str(result.relevant_variables()))
    _whole1, result1 = slice_of(os.path.join(EX, "ab-1.rebeca"), "m1")
    check("z is relevant in the original",
          "A.m1.z" in result1.relevant_variables(),
          str(result1.relevant_variables()))

    print("\nEquivalence")
    check("every example is equivalent to itself",
          all(compare(slice_of(os.path.join(EX, f), o)[1].graph,
                      slice_of(os.path.join(EX, f), o)[1].graph).equivalent
              for f, o in [("ab-1.rebeca", "m1"), ("ab-2.rebeca", "m1"),
                           ("1-heater.rebeca", "getSense"),
                           ("2-heater.rebeca", "getSense")]))
    a = slice_of(os.path.join(EX, "ab-1.rebeca"), "m1")[1].graph
    b = slice_of(os.path.join(EX, "ab-2.rebeca"), "m1")[1].graph
    check("the article's two AB models are not slice equivalent",
          not compare(a, b).equivalent)

    print("\nThe heater case study of Section 4")
    obs = parse_observables(os.path.join(EX, "heater-observable.txt"))
    left = load(os.path.join(EX, "1-heater.rebeca"), obs)
    right = load(os.path.join(EX, "2-heater.rebeca"), obs)
    strict = compare(left.result.graph, right.result.graph)
    check("keeping the known rebecs, the slices differ only in the main "
          "instantiation statement",
          not strict.equivalent and len(strict.reasons) == 2
          and all("controller(" in r for r in strict.reasons),
          str(strict.reasons))
    check("the Notifyer rebec is outside the slice",
          not any(n.content == ("C", "Notifyer")
                  for n in right.result.graph.nodes.values()))
    check("both sides have the same relevant messages",
          left.result.relevant_messages() == right.result.relevant_messages())
    check("both sides have the same relevant variables",
          left.result.relevant_variables() ==
          right.result.relevant_variables())
    default = compare(ignore_known_rebecs(left.result.graph, left.graph),
                      ignore_known_rebecs(right.result.graph, right.graph))
    check("by default the Section 4 case study comes out equivalent, as the "
          "article says", default.equivalent, str(default.reasons))

    print("\nIntra-rebec dependence")
    _m, strict = graph_of_strict(os.path.join(EX, "1-heater.rebeca"))
    _m2, loose = graph_of(os.path.join(EX, "1-heater.rebeca"))
    strict_targets = {s for s, _t in edge_labels(strict, EdgeKind.I)}
    loose_targets = {s for s, _t in edge_labels(loose, EdgeKind.I)}
    check("the literal reading misses  heating_active = true",
          "heating_active = true" not in strict_targets)
    check("the default reading keeps it, so it stays in the slice",
          "heating_active = true" in loose_targets)

    print("\nObservable files")
    check("a bare name selects every message server with that name",
          len(parse_observable_text("m1").entries) == 1)
    check("'time' is ignored",
          parse_observable_text("m1, time").ignored == ["time"])
    check("comments and newlines are allowed",
          [m for _o, m in parse_observable_text(
              "# c\nm1,\nm2 # tail\n").entries] == ["m1", "m2"])
    check("an empty observable set is an error", rejects_obs(""))
    check("message names match case-insensitively, as the tiny-twin "
          "observable files are lowercased",
          len(slice_of(os.path.join(EX, "1-heater.rebeca"),
                       "controller.getsense")[1].roots) == 1)
    check("an exact match wins over a case-insensitive one",
          len(slice_of(os.path.join(EX, "1-heater.rebeca"),
                       "Controller.getSense")[1].roots) == 1)
    check("a message that exists nowhere is reported unmatched",
          slice_of(os.path.join(EX, "1-heater.rebeca"),
                   "noSuchMessage")[1].unmatched == ["noSuchMessage"])

    print("\nAgainst measured tiny twins (../10, skipped if absent)")
    ten = os.path.normpath(os.path.join(HERE, "..", "10"))
    if not os.path.isdir(ten):
        print("  skip  ../10 is not present")
    else:
        def slice10(model, obs, params):
            m = parse_file(os.path.join(ten, model))
            g = build_rdg(m, model)
            rc = {i.rebec_name: i.class_name for i in m.instances}
            return observable_slice(
                g, parse_observables(os.path.join(ten, obs)), rc,
                observe_parameters=params).graph
        # measured: the ring-C edit leaves ring P's twin byte-identical and
        # moves ring C's twin from 20 to 12 states.
        check("ring P is unaffected by an edit inside ring C",
              compare(slice10("model.rebeca", "observable_ringP.txt", True),
                      slice10("model_A.rebeca", "observable_ringP.txt", True)
                      ).equivalent)
        check("ring C is affected by it, with --observe-parameters",
              not compare(
                  slice10("model.rebeca", "observable_ringC.txt", True),
                  slice10("model_A.rebeca", "observable_ringC.txt", True)
              ).equivalent)

    print("\nThe samples of the old article (article/old/samples)")
    old = os.path.join(HERE, "article", "old", "samples")
    if not os.path.isdir(old):
        print("  skip  article/old/samples is not present")
    else:
        def old_slice(rel, obs):
            path = os.path.join(old, rel)
            m = parse_file(path)
            g = build_rdg(m, os.path.basename(rel))
            rc = {i.rebec_name: i.class_name for i in m.instances}
            r = observable_slice(g, parse_observable_text(obs), rc)
            return ignore_known_rebecs(r.graph, g)

        # ObservableActions is the same in all four; each adds more of an
        # internal rebec that no observable message depends on.
        family_a = ["sim-obs-internal/1/1-sim.rebeca",
                    "sim-obs-internal/2/2-sim.rebeca",
                    "sim-obs-internal/3/3-sim.rebeca",
                    "two-observable-in-bag/4/4-sim.rebeca"]
        base = old_slice(family_a[0], "o1, o2, o3, o4")
        check("adding an internal rebec outside the slice keeps the four "
              "sim-obs-internal models equivalent",
              all(compare(base, old_slice(rel, "o1, o2, o3, o4")).equivalent
                  for rel in family_a[1:]))

        # Two observable messages live in the bag at once; the revisions add
        # an internal rebec and then give it nondeterminism of its own.
        family_b = ["two-observable-in-bag/1/1-obs.rebeca",
                    "two-observable-in-bag/2/2-obs.rebeca",
                    "two-observable-in-bag/3/3-obs.rebeca"]
        base_b = old_slice(family_b[0], "o1, o2, o3")
        check("the three two-observable-in-bag models are equivalent",
              all(compare(base_b, old_slice(rel, "o1, o2, o3")).equivalent
                  for rel in family_b[1:]))
        check("models from the two families are not equivalent",
              not compare(base_b, old_slice(family_a[0], "o1, o2, o3")
                          ).equivalent)
        check("the old article's heater pair matches the one in examples/",
              compare(old_slice("heater/1/1-heater.rebeca", "getSense"),
                      old_slice("heater/2/2-heater.rebeca", "getSense")
                      ).equivalent)

    print("\nThe ten case studies next door (skipped if absent)")
    samples = [(str(n), os.path.normpath(os.path.join(HERE, "..", str(n))))
               for n in range(1, 11)]
    if not all(os.path.isdir(d) for _n, d in samples):
        print("  skip  ../1 .. ../10 are not all present")
    else:
        jobs = [(n, os.path.join(d, "model.rebeca"),
                 os.path.join(d, "observable_messages.txt"))
                for n, d in samples[:9]]
        jobs += [("10 P", os.path.join(samples[9][1], "model.rebeca"),
                  os.path.join(samples[9][1], "observable_ringP.txt")),
                 ("10 C", os.path.join(samples[9][1], "model.rebeca"),
                  os.path.join(samples[9][1], "observable_ringC.txt"))]
        built = []
        for name, model, obs in jobs:
            m = parse_file(model)
            graph = build_rdg(m, name)
            rc = {i.rebec_name: i.class_name for i in m.instances}
            res = observable_slice(graph, parse_observables(obs), rc)
            built.append((name, model, obs, m, graph, res))
        check("all ten models parse and build an RDG", len(built) == 11)
        check("no observable message goes unmatched in any sample",
              all(not r.unmatched for *_x, r in built),
              str([(n, r.unmatched) for n, *_x, r in built if r.unmatched]))
        check("no sample slices to nothing",
              all(r.graph.nodes for *_x, r in built),
              str([n for n, *_x, r in built if not r.graph.nodes]))
        check("every sample is equivalent to itself",
              all(compare(r.graph, r.graph).equivalent for *_x, r in built))
        bad = mutation_survey(built)
        check("an edit inside the slice is always caught and an edit "
              "outside it never is, across all ten samples",
              not bad, "; ".join(bad))

    print("\nEnd to end")
    with tempfile.TemporaryDirectory() as tmp:
        status = run(os.path.join(EX, "1-heater.rebeca"),
                     os.path.join(EX, "2-heater.rebeca"),
                     os.path.join(EX, "heater-observable.txt"),
                     tmp, quiet=True)
        produced = sorted(os.listdir(tmp))
        check("exit status is 0 when the slices are equivalent", status == 0)
        check("both RDGs, both slices, a legend and result.txt are written",
              produced == ["1-heater-rdg.dot", "1-heater-slice.dot",
                           "2-heater-rdg.dot", "2-heater-slice.dot",
                           "legend.dot", "result.txt"], str(produced))
        with open(os.path.join(tmp, "result.txt"), encoding="utf-8") as fh:
            report = fh.read()
        check("result.txt states the verdict", "EQUIVALENT" in report)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


def mutation_survey(built):
    """Bump an integer literal in one statement inside the slice and one
    outside it; the first must be caught, the second must not."""
    import re as _re
    problems = []
    for name, model, obs, _m, graph, res in built:
        source = open(model, encoding="utf-8").read().splitlines()
        picks = {}
        for node in sorted(graph.nodes.values(), key=lambda n: n.line):
            if node.kind is not NodeKind.S or not node.line:
                continue
            line = source[node.line - 1]
            if not _re.search(r"\b\d+\b", line) or "reactiveclass" in line:
                continue
            where = "inside" if node.id in res.kept else "outside"
            picks.setdefault(where, (node.line, node.label))
        for where, expected in (("inside", False), ("outside", True)):
            if where not in picks:
                continue
            lineno, label = picks[where]
            edited = list(source)
            edited[lineno - 1] = _re.sub(
                r"\b(\d+)\b", lambda mm: str(int(mm.group(1)) + 7),
                edited[lineno - 1], count=1)
            other = parse_source("\n".join(edited) + "\n", model)
            other_graph = build_rdg(other, name)
            rc = {i.rebec_name: i.class_name for i in other.instances}
            other_res = observable_slice(
                other_graph, parse_observables(obs), rc)
            got = compare(res.graph, other_res.graph).equivalent
            if got is not expected:
                problems.append(
                    f"sample {name}: editing {label!r} {where} the slice gave "
                    f"{'equivalent' if got else 'not equivalent'}")
    return problems


def graph_of_strict(path):
    model = parse_file(path)
    return model, build_rdg(model, "strict", strict_intra_rebec=True)


def rejects(source):
    try:
        parse_source(source)
    except RebecaError:
        return True
    return False


def rejects_obs(text):
    try:
        parse_observable_text(text)
    except ObservableError:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
