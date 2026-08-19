# Top-level orchestration. Every target must be reproducible from a clean checkout.

.PHONY: all env-check mirrors bitstreams measure figures paper clean manifest

all: env-check mirrors bitstreams measure figures paper

env-check:          ## verify toolchain, platform, device visibility, permissions
	@bash scripts/env_check.sh

mirrors:            ## build software decoders, run mirror test suite (no hardware needed)
	@python -m pytest models/tests -v

bitstreams:         ## synthesise and link all kernels (long: hours)
	@$(MAKE) -C rtl/rep3
	@$(MAKE) -C rtl/shor913
	@$(MAKE) -C rtl/steane713

measure:            ## run experiments E01 to E08 against hardware
	@for d in experiments/E0*/ ; do echo "== $$d"; ( cd $$d && ./run.sh ) || exit 1; done
	@$(MAKE) manifest

figures:            ## regenerate every figure from experiments/*/processed/
	@for d in experiments/E0*/ ; do [ -f $$d/plot.py ] && python $$d/plot.py || true; done

paper:              ## build the manuscript PDF
	@bash paper/build.sh

manifest:           ## checksum every evidence file
	@cd evidence && find . -type f ! -name MANIFEST.sha256 -exec sha256sum {} + > MANIFEST.sha256
	@echo "evidence manifest updated"

clean:
	@rm -rf paper/*.aux paper/*.log paper/*.out
