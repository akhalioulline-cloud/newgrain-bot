# Flagleaf / NewGrain — common commands. Run `make` for the list.
# Committed to the repo, so they work the same on every machine.
.PHONY: help handoff pickup save restore deploy

help:
	@echo "Flagleaf — make targets:"
	@echo "  make handoff   leaving a machine: save context + commit + push"
	@echo "  make pickup    arriving: pull + restore context (then run: claude)"
	@echo "  make save      save Claude context snapshot into the repo"
	@echo "  make restore   restore Claude context onto this machine"
	@echo "  make deploy    rsync to prod + rebuild bot (avoid while Almas uploads)"

handoff:
	@./scripts/handoff.sh

pickup:
	@./scripts/pickup.sh

save:
	@./scripts/claude-memory.sh save

restore:
	@./scripts/claude-memory.sh restore

deploy:
	@./scripts/deploy.sh
