.PHONY: setup test lint format typecheck check package clean schema-sync schema-regen

# Local dev environment setup. NOT needed at deploy time.
# Runtime (scripts/) is stdlib-only; this is for developer convenience.
#
# Interpreter is pinned to python3.12 — see dev-docs/python-version.md
# for why. Using a plain `python3` here risks picking up a newer
# interpreter where the coverage harness silently fails.
setup:
	python3.12 -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements-dev.txt

# Run the full test suite with line coverage.
# Fails (exits non-zero) if line coverage across scripts/ drops below 90%.
test:
	./tests/run.sh

# Lint without modifying files. Reports style and common-bug issues.
lint:
	./.venv/bin/ruff check scripts tests tools
	./.venv/bin/ruff format --check scripts tests tools

# Apply automatic fixes and formatting in place.
format:
	./.venv/bin/ruff check --fix scripts tests tools
	./.venv/bin/ruff format scripts tests tools

# Light-touch static type checking.
typecheck:
	./.venv/bin/mypy scripts tests tools

# One-shot developer gate: lint, types, tests. Use this before committing.
check: lint typecheck test

# Build a deployable zip under dist/. Contains only the runtime tree
# (scripts/, an empty db/datasource.db built from the schema fixture,
# and Makefile/README.md if they exist). Excludes tests/, .kiro/, dev-docs/,
# tools/, dev config, and caches. See tools/package.py for details.
#
# Depends on schema-sync so the zip always ships the freshest schema.
package: schema-sync
	python3 tools/package.py

# Copy the canonical schema fixture into scripts/ so init_db.py and
# tools/package.py._empty_db both read the same bytes. Safe to run
# repeatedly. tests/fixtures/schema.sql stays the human-readable,
# git-diffable source of truth; scripts/schema.sql is the mechanical
# copy for runtime use.
schema-sync:
	cp tests/fixtures/schema.sql scripts/schema.sql

# Regenerate tests/fixtures/schema.sql from the real db/datasource.db
# (via tests/fixtures/dump_schema.py), then copy the result into
# scripts/ so runtime and packaging stay in sync. Two-step by design
# so schema changes are reviewed in the fixture before propagating.
schema-regen:
	python3 tests/fixtures/dump_schema.py
	$(MAKE) schema-sync

# Remove coverage artifacts, review output, caches, the local venv, and
# any previously packaged zips.
clean:
	rm -rf .trace output .pytest_cache .ruff_cache .mypy_cache .venv dist .coverage_data
	rm -f .coverage .coverage.* .coveragerc sitecustomize.py
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
