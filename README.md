# AdaptChecker — observable RDG slice comparison for Timed Rebeca

Given **two Timed Rebeca models** and **one file naming the observable
messages**, this tool builds the Rebeca Dependence Graph of each model, takes
the observable slice of each, and answers one question:

> Are the two observable slices equivalent?

If they are, the soundness theorem of Section 3 says the two models are weak
timed bisimilar with respect to `O`, so a tiny twin built for one of them is
still valid for the other and does not have to be regenerated.

Everything is implemented from the definitions in
[`article/new/3-RDG.tex`](article/new/3-RDG.tex).

## Requirements

**Python 3.8 or newer, and nothing else.** No `pip install`, no virtualenv, no
third-party package — the lexer, parser, graph builder, slicer, isomorphism
check and DOT writer are all standard library.

[Graphviz](https://graphviz.org/) (`dot`) is **optional**. The tool writes
`.dot` files; you only need Graphviz if you want to turn them into pictures.

## Running it

```bash
python3 adaptcheck.py <model1.rebeca> <model2.rebeca> <observables.txt> -o <outdir>
```

The worked example, which is the case study of Section 4 — the heater model and
the revision that adds a `Notifyer` rebec:

```bash
python3 adaptcheck.py examples/1-heater.rebeca examples/2-heater.rebeca \
        examples/heater-observable.txt -o out
```

or just

```bash
./run-example.sh
```

To check the tool against the article's own examples:

```bash
python3 selftest.py
```

### Options

| flag | meaning |
|---|---|
| `-o DIR`, `--output DIR` | output folder, created if missing (default `out`) |
| `-q`, `--quiet` | print only the verdict, one word |
| `-v`, `--verbose` | print the whole of `result.txt` instead of the summary |
| `--strict-intra-rebec` | read the intra-rebec edge definition literally (see below) |
| `--strict-main-args` | keep known rebecs inside the content of a `main` instantiation (see below) |
| `--observe-parameters` | treat the arguments of the observable messages as observable too (see below) |

Exit status is **0** when the slices are equivalent, **1** when they are not,
and **2** when an input could not be read, so it drops straight into a script.

## Input

### The two models

Timed Rebeca in the fragment of Section 2: reactive classes with known rebecs,
state variables, a constructor and message servers; assignment, nondeterministic
assignment `x = ?(e1, e2)`, conditionals, and sends `r.m(args) after(t)`.
`delay` and `deadline` are outside the fragment and are rejected with the line
number rather than quietly ignored.

### The observable messages

A text file naming the messages of `O`, comma- or newline-separated. `#` and
`//` start a comment.

```
# Observable messages
Controller.getSense(int), HC_Unit.activateh(), HC_Unit.switchoff(), time
```

* A **bare name** — `getSense` — selects every message server with that name,
  which is what the definition of `node(G, O)` says.
* A **qualified name** — `Controller.getSense` or `controller.getSense` —
  narrows it to one reactive class. The owner is matched case-insensitively
  against class names and against rebec names declared in `main`.
* **Case.** An exact match wins; failing that the message name is matched
  case-insensitively, so the all-lowercase observable files written for the
  tiny-twin tooling (`hfilter.newsample`) find `newSample`.
* If none of the observable messages exists in one of the models its slice
  would be empty and any answer vacuous, so that is an error, not an
  `EQUIVALENT`. The message lists what the model does offer.
* A parameter list, `getSense(int)`, is accepted and ignored.
* `time` is accepted and ignored: it is a tiny-twin convention, not a message.

## Output

Everything lands in the one output folder:

| file | what it is |
|---|---|
| `<model1>-rdg.dot` | the whole RDG of the first model, with the slice highlighted |
| `<model2>-rdg.dot` | the same for the second model |
| `<model1>-slice.dot` | `Slice(RDG(M1), O)` on its own |
| `<model2>-slice.dot` | `Slice(RDG(M2), O)` on its own |
| `legend.dot` | the key on its own, for use as a figure |
| `result.txt` | the verdict and everything behind it |

### How the graphs are drawn

The `.dot` files follow the RDG figures drawn for the article: boxes for
everything with an ellipse for a class-object node, an HTML label of the form
*number* over *syntax*, one cluster per reactive class labelled `Model$Class`
plus one for `main`, and no edge labels — the colour says which dependence it
is and a legend inside the graph gives the key.

| fill | node |
|---|---|
| green | the `main` entry |
| orange | an observable message-server entry, that is `node(G, O)` |
| yellow | anything else in the slice |
| none | outside the slice |

| edge | dependence |
|---|---|
| green | member, `E_M` |
| black | control, `E_C` |
| blue | data, `E_D` |
| blue dotted | intra-rebec, `E_I` |
| black, unconstrained | activation, `E_A` |
| purple | binding, `E_B` |

The same key is written to `legend.dot` on its own, which also shows the six
node kinds of the new definition.

The terminal gets a short summary; `result.txt` keeps the rest.

```
$ ./run-example.sh

O = Controller.getSense, HC_Unit.activateh, HC_Unit.switchoff

  1-heater                 RDG   55 nodes   slice   46  (84%)
  2-heater                 RDG   68 nodes   slice   46  (68%)

  EQUIVALENT

  6 files in out/ -- details in result.txt
```

When the slices differ it names what differs, most telling first, and says
how many more there are:

```
  NOT EQUIVALENT
    only in 1-heater: N_S Controller controller(hc_unit):()
    only in 2-heater: N_S Controller controller(hc_unit, notifyer):()
```

`-q` prints just `EQUIVALENT` or `NOT EQUIVALENT`; `-v` prints the whole
report.

`result.txt` carries the verdict, the reason when the slices differ, and for
each model: the RDG size broken down by node and edge kind, the slice size and
its share of the RDG, the relevant variables `RV`, the relevant message names
`RM`, and the list of nodes that fall **outside** the slice — which is the list
of places the model can be edited without invalidating the twin.

To draw the graphs:

```bash
dot -Tpng out/1-heater-rdg.dot -o out/1-heater-rdg.png
```

## What is implemented

Section 3, definition by definition.

**RDG(M) = (N, E)** with six node kinds and six edge kinds:

| set | node kind | one per |
|---|---|---|
| `N_C` | class-object | reactive class |
| `N_E` | entry | `main`, each constructor, each message server |
| `N_FP` | formal-in parameter | parameter of a message server or constructor, as the assignment `v = v_in` |
| `N_AP` | actual-in parameter | argument of a send, as the assignment `v_in = expr` |
| `N_SV` | state variable | state variable declaration |
| `N_S` | statement | assignment, nondeterministic assignment, conditional, send, object instantiation in `main` |

| set | edge kind | from → to |
|---|---|---|
| `E_C` | control | entry → its formal-in nodes and its body; conditional → each branch, labelled `true`/`false`; send → its actual-in nodes; instantiation → the class-object node |
| `E_D` | data | both clauses of the data-dependence definition of Section 2: a definition reaching a use with no intervening definition, and two definitions of one variable that both reach a common use |
| `E_I` | intra-rebec | a state variable written by one activation of a message server and read by a later one |
| `E_M` | member | class-object → its state variables, its constructor and its message servers |
| `E_B` | binding | actual-in → the matching formal-in |
| `E_A` | activation | send → the entry node of the message server it activates |

**Slice(G, O)** is backward reachability from the entry nodes of the observable
messages, together with the state-variable and formal-in declarations that the
reached statements use or define.

**RDG equivalence** is a bijection preserving the kind and the content of every
node and preserving every edge. The article lists the edge conditions one kind
at a time and leaves `E_B` and `E_I` off that list; we require the whole edge
set to correspond, including the `true`/`false` labels, so the check is at
least as strong as the definition. The bijection is found by colour refinement
followed by backtracking.

**Node content** follows the article: a class-object node is its class name, an
entry node its qualified name (`main`, `constructor`, or the message-server
name), a state-variable or parameter node its name and type, and a statement
node its form together with the identifiers, expressions, receiver, target
message server and timing annotation occurring in it. The argument expressions
of a send are **not** repeated in the send statement's content, because the
article already models them as separate actual-in nodes.

## Where the article's text and its examples disagree

Running the tool on the article's own figures turned up two places where the
definitions as written do not give the answer the article states. Each is
behind a flag, so you can reproduce either reading.

### 1. The intra-rebec edge — `--strict-intra-rebec`

> `E_I` … exists between **the last statement** of a message server which is
> assigning a value to a variable and the first use of that variable in
> **another** message server.

Taken literally this misses two things:

* **"the last statement".** With a conditional there can be one last
  assignment per branch. In `1-heater.rebeca`, `getSense` assigns
  `heating_active` in both branches; only `heating_active = false` is textually
  last, so `heating_active = true` gets no outgoing edge at all, falls outside
  the slice, and an edit to it would be reported as harmless when it is not.
* **"another".** A rebec handles the same message again later, so a message
  server depends on its own previous activation. `getSense` is the only message
  server that touches `heating_active`, so under the literal reading that
  dependency disappears entirely.

By default the tool takes the reading these are short for: every definition
still live where the body ends, to every use that reads the value the body
started with, in any message server of the class **including the same one**.
That only ever adds edges, so it can never turn a real difference into a false
"equivalent".

`--strict-intra-rebec` gives the literal reading. It reproduces the Example
after Definition "Observable RDG Slice" exactly: for
`ab-2.rebeca` with `O = {m1}` the nodes outside the slice are precisely
`z_in = true`, `z_in = x || y`, `z = z_in` and `x = !x`, the four the article
names. By default `x = !x` stays in, because `m2` reads `x` on its next
activation and so the edit does reach `m1`.

### 2. The arguments of an observable message — `--observe-parameters`

The transition label of the operational semantics is the message name: rule
`TakeMessage` gives `(s,t) --m--> ...`, with no parameters in the label. The
slice follows suit, and the article's own example depends on it — `z` is called
"useless in this revision" precisely because `m1`'s body ignores it, even though
`m1` is the observable message and the value passed to it still differs.

So by default an edit that changes only *what value* an observable message
carries is reported as equivalent. That is right for the equivalence the
article defines, and wrong for a tiny twin, whose actions are labelled
`rebec.msgsrv[args]`.

`--observe-parameters` adds the formal-in nodes of the observable message
servers to the roots of the slice, so backward reachability also pulls in the
actual-in nodes that supply their arguments and everything those depend on.
The proof of the soundness theorem needs this: it compares message bags as
`(x, z, m, p, a)` tuples, parameter valuation `p` included.

### 3. Known rebecs in a `main` instantiation — `--strict-main-args`

Two sentences of Section 3 pull in opposite directions. The content of a
statement node is "its statement form together with the identifiers … occurring
in it", which would include the known rebecs an instantiation binds; but the
RDG is said to be simpler than its ancestor "due to **ignoring known rebecs**".

Nothing in the graph represents the wiring — a send resolves to the *class* of
its receiver, so the activation edge points at a class's message server, not at
a rebec. Keeping the known rebecs inside `cont()` would smuggle back in,
through the statement text, the one thing the definition says it leaves out.
It is also what made the Section 4 case study come out unequal, on this single
difference and nothing else:

```
only on the left  : Controller controller(hc_unit):()
only on the right : Controller controller(hc_unit, notifyer):()
```

So the tool ignores them by default, and the heater pair comes out
`EQUIVALENT`, as Section 4 says. Known rebecs whose class *is* in the slice are
still kept, so a genuine rewiring among the rebecs that matter remains visible,
and the drawn label always shows the statement as written.
`--strict-main-args` restores the literal text comparison.

When the other reading of `E_I` would flip the verdict, the report says so
rather than leaving you to find out.

## Checked against measured behaviour

`selftest.py` runs 48 checks in about half a second. They pin the tool to the
article's own worked examples and, when the ten case studies are present next
to this folder, to behaviour that was actually measured.

### The samples of the old article

`article/old/samples/` holds three families of models built to exercise the
analysis. Each family shares one observable class and adds progressively more
of an internal rebec that no observable message depends on — the
"adding or removing a rebec whose class, state variables, message servers, and
dependencies are entirely outside the observable RDG slice" revision of the
Discussion. All of them come out as they should:

| family | `O` | models | verdict |
|---|---|---|---|
| `sim-obs-internal` 1, 2, 3 and `two-observable-in-bag/4` | `o1 o2 o3 o4` | one observable class, an internal rebec that grows from nothing to a nondeterministic one with its own state | all four equivalent |
| `two-observable-in-bag` 1, 2, 3 | `o1 o2 o3` | two observable messages in the bag at once, then an internal rebec, then one with a nondeterministic branch | all three equivalent |
| across the two families | `o1 o2 o3` | different observable classes | not equivalent |
| `heater` 1 and 2 | `getSense` | the same pair as `examples/` | equivalent |

### The ten case studies

All ten parse, none has an unmatched observable message, none slices to
nothing, and each is equivalent to itself. The slice keeps between 2.9% and
61.7% of the RDG, and what that varies with is where `O` sits, not how big the
model is:

| # | RDG nodes | slice | share |    | # | RDG nodes | slice | share |
|---|---|---|---|---|---|---|---|---|
| 1 | 327 | 45 | 13.8% | | 6 | 148 | 49 | 33.1% |
| 2 | 417 | 43 | 10.3% | | 7 | 277 | 56 | 20.2% |
| 3 | 430 | 23 | 5.3% | | 8 | 221 | 115 | 52.0% |
| 4 | 473 | 36 | 7.6% | | 9 | 282 | 174 | 61.7% |
| 5 | 515 | 15 | 2.9% | | 10 | 87 | 32 / 47 | 37% / 54% |

The largest — 35 reactive classes, 515 RDG nodes — is parsed, built, sliced and
compared in about a tenth of a second.

### Does the slice discriminate?

For each sample, bump an integer literal in one statement **inside** the slice
and in one **outside** it. All 22 mutations behave: every edit inside is
caught, no edit outside is:

| # | edit inside the slice | verdict | edit outside it | verdict |
|---|---|---|---|---|
| 1 | `self.scanSpeed() after(1)` | not equivalent | `self.scanPower() after(3)` | equivalent |
| 4 | `amps = ?(1, 2, 3)` | not equivalent | `amps = 1` | equivalent |
| 7 | `self.sample() after(5)` | not equivalent | `h = 2` | equivalent |
| 9 | `fusion.newCloud()` | not equivalent | `self.publish() after(6)` | equivalent |
| … | one row per sample | | | |

### Against tiny twins that were actually generated

Sample 10 ships two edits of the message server its two cycles share, and the
twins for both were derived and compared with `ltscompare`. With
`--observe-parameters` — the right mode, because tiny-twin actions are labelled
`rebec.msgsrv[args]` — the tool agrees with all four, including the accept:

| comparison | measured twin | tool |
|---|---|---|
| `model` vs `model_A`, ring P | byte-identical, 23 states | equivalent |
| `model` vs `model_A`, ring C | 20 states becomes 12 | not equivalent |
| `model` vs `model_B`, ring P | 23 states becomes 26 | not equivalent |
| `model` vs `model_B`, ring C | 20 states becomes 15 | not equivalent |

### Deleting a module nothing depends on

Every sample has a logger or telemetry sink that nothing reads back. Deleting
it leaves all the twins equal, measured with `ltscompare`:

| # | module removed | tool | measured twin |
|---|---|---|---|
| 1 | `ScadaLogger` | equivalent | equal |
| 2 | `DiagLogger` | equivalent | equal |
| 3 | `PropTelemetry` | equivalent | equal |
| 4 | `MeterDisplay` | equivalent | equal |
| 5 | `MasterCautionPanel` | equivalent | equal |
| 6 | `TelemetryLogger` | equivalent | not derived |
| 7 | `FlightRecorder` | equivalent | equal |
| 8 | `Logger` | equivalent | equal |
| 9 | `RobotStateView` | equivalent | equal |
| 10 | `Statistics`, both rings | equivalent | equal |

All eleven agree with the twins, and nothing is rejected conservatively.
`--strict-main-args` turns six of them back into rejections, each on the one
argument-list difference described above.

## Examples

| file | what it is |
|---|---|
| `examples/1-heater.rebeca` | the heater model `M` of Section 4 |
| `examples/2-heater.rebeca` | the revision `M'`, which adds a `Notifyer` rebec |
| `examples/heater-observable.txt` | the heater-control messages |
| `examples/ab-1.rebeca` | the `A`/`B` model of the article's first RDG figure |
| `examples/ab-2.rebeca` | the revision in which `m1` sends `m2` unconditionally |
| `examples/ab-observable.txt` | `O = {m1}` |
| `examples/expected-output/` | what a run of the heater pair produces, so you can see the output without running anything |

## Layout

```
adaptcheck.py        the runner -- python3 adaptcheck.py ...
selftest.py          checks the tool against the article's examples
rdgcompare/
  rebeca.py          lexer, AST and parser for the Timed Rebeca fragment
  rdg.py             the RDG and its construction
  slicing.py         observable messages, Slice(G,O), RV and RM
  compare.py         RDG equivalence
  dot.py             Graphviz output
  cli.py             argument handling and the report
examples/            the models above, and one sample output
article/             the paper this implements
oldCodes/            the earlier RDG and tiny-twin tools, kept for reference
```
