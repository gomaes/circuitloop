"""circuitloop: AI-driven autonomous circuit design with deterministic verification."""

__version__ = "0.1.0"

EXIT_OK = 0
EXIT_DESIGN_FAILED = 1
EXIT_ENV_ERROR = 2
EXIT_TAMPERED = 3
EXIT_SPEC_INFEASIBLE = 4  # the spec asks for more than the parts allow (proposal in relaxation.json)
