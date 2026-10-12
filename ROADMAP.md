# Roadmap toward independent qualification

Ordered by importance for credibility, not by effort.

| # | Item | Why |
|---|---|---|
| R1 | Compare Pc against NASA CARA `Pc2D_Foster` test cases and published Alfano test cases | Independent verification of the probability numerics against an operationally used implementation |
| R2 | Covariance propagation (STM with the numerical propagator) and Pc at computed TCAs for ephemerides with covariance | Removes the "CDM-only Pc" limitation |
| R3 | Orekit-based numerical propagation (Java via orekit_jpype) with documented force models | Higher-fidelity propagation and covariance for operator states |
| R4 | 3D / non-linear Pc for low-velocity or long encounters (e.g. CARA Pc3D or Monte Carlo with full dynamics) | Covers cases flagged by the 2D applicability heuristics |
| R5 | Chunked state grid and parallel propagation; full-catalogue benchmarks on documented hardware | Scale beyond ~2,000 objects with bounded memory |
| R6 | Verify CCSDS editions; add OEM/CDM XML; schema-validate exports against official XSDs | Interoperability evidence |
| R7 | OIDC (authorisation code + PKCE) login; organisation-level access policies | Standards-based identity |
| R8 | Shared rate limiting and job quotas across replicas; S3-compatible object store | Multi-node deployment |
| R9 | Automated retention purge and verified deletion of object-store files | Data governance |
| R10 | Authorised labelled historical data for ML; drift monitoring on real inputs | Any claim about ML usefulness |
| R11 | Third-party security assessment and penetration test | Security assurance |
| R12 | Independent review by qualified conjunction-assessment analysts; a documented verification & validation plan with acceptance criteria | Prerequisite for any operational evaluation |
