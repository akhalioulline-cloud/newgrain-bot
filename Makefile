# Flagleaf / NewGrain — common commands. Run `make` for the list.
# Committed to the repo, so they work the same on every machine.
.PHONY: help handoff pickup save restore deploy thread-out thread-in

help:
	@echo "Flagleaf — make targets:"
	@echo "  make handoff     leaving a machine: save context + commit + push"
	@echo "  make pickup      arriving: pull + restore context (then run: claude)"
	@echo "  make thread-out  leaving: send this session transcript to the other Mac"
	@echo "  make thread-in   arriving: receive the transcript (then: claude --resume)"
	@echo "  make save        save Claude context snapshot into the repo"
	@echo "  make restore     restore Claude context onto this machine"
	@echo "  make deploy      rsync to prod + rebuild bot (avoid while Almas uploads)"

handoff:
	@./scripts/handoff.sh

pickup:
	@./scripts/pickup.sh

thread-out:
	@./scripts/thread-out.sh

thread-in:
	@./scripts/thread-in.sh

save:
	@./scripts/claude-memory.sh save

restore:
	@./scripts/claude-memory.sh restore

deploy:
	@./scripts/deploy.sh
