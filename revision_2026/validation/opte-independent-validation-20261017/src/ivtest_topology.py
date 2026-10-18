"""Test only (not part of the validator): compare the rebuilt topology with the original builder on one input."""
import sys, json, numpy as np
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + '/frozen'); sys.path.insert(0, sys.argv[1] + '/frozen/vendor')
sys.path.insert(0, sys.argv[3])
import validate_case as VC
import instance as _i, master as _m, colgen as _c
class V: Instance, Trip, Column = _i.Instance, _i.Trip, _m.Column
raw = json.load(open(sys.argv[2]))['record']; inst = VC.instance_from_record(raw, V)
top = VC.Topology(inst)
from extension_models import build_extended_graph
g = build_extended_graph(inst)
print({'nodes': (top.n_nodes, g.n_nodes), 'arcs': (top.n_arcs, g.n_arcs),
       'states_equal': bool(np.array_equal(top.states, g.states)), 'tail': bool(np.array_equal(top.tail, g.tail)),
       'head': bool(np.array_equal(top.head, g.head)), 'kind': bool(np.array_equal(top.kind, g.kind)),
       'task': bool(np.array_equal(top.task, g.task)), 'energy': bool(np.allclose(top.energy, g.energy, atol=0)),
       'source_sink': (top.source, top.sink, g.source, g.sink)})
