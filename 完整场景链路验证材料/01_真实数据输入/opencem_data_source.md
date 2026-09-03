# OpenCEM replay fixture

`2025-07-a.csv` is an unmodified public measurement partition downloaded from the official
[OpenCEM dataset repository](https://github.com/OpenCEM-platform/opencem-dataset). SHA-256:
`9094f34779cc58046eab3a3ab0bb6a355db5ec0e0fccc254dfae762d0855f907`.

EnergyMesh selects the most complete measured UTC day, aggregates the two inverter streams into
96 quarter-hour intervals, and records the source row count in every normalized Snapshot. The
tariff and protected-load policy are explicit EnergyMesh replay configuration, not OpenCEM
measurements.

OpenCEM dataset metadata identifies the data license as CC BY 4.0. Cite:

T. S. Bartels, R. Wu, X. Lu, Y. Lu, F. Xia, H. Yang, Y. Chen, and T. Li,
“Bridging Natural Language and Microgrid Dynamics: A Context-Aware Simulator and Dataset,” 2026,
arXiv:2604.05429.
