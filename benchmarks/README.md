# Advisory benchmark

Step 13 runs fresh sequential baseline/candidate trial pairs and unchanged A/A
controls, with raw warmups, attempted timings, errors and descriptive summaries.
Step 14 captures separate diagnostic plans. See [the protocol](../docs/observations.md)
and `examples/orders/benchmark.yml` / `examples/orders/plans.yml`.

The default benchmark uses small synthetic data to exercise the protocol. It does
not claim an index speedup, calibrated production capacity, or a strict CI gate.
